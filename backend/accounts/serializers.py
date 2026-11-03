from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    # Role / tenant / quotas are READ-ONLY here: a user can never promote themselves or change
    # their own limits through /auth/me or registration. Only company/platform admin APIs can.
    quota = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name", "company_name", "date_joined",
                  "role", "company", "daily_quota", "monthly_quota", "quota"]
        read_only_fields = ["id", "date_joined", "role", "company", "daily_quota", "monthly_quota", "quota"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_superuser:          # also covers superusers created before the role was synced on save
            data["role"] = "super_admin"
        return data

    def get_company(self, obj):
        return {"id": obj.company_id, "name": obj.company.name} if obj.company_id else None

    def get_quota(self, obj):
        from tenancy.quota import quota_snapshot

        return quota_snapshot(obj)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "password_confirm", "first_name", "last_name", "company_name"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Allows login with either username or email in the 'username' field."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["username"] = user.username
        return token

    def validate(self, attrs):
        login_value = attrs.get(self.username_field)
        if login_value and "@" in login_value:
            try:
                user_obj = User.objects.get(email__iexact=login_value)
                attrs[self.username_field] = user_obj.username
            except User.DoesNotExist:
                pass
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data