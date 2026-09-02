from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import EmailTemplate
from .serializers import EmailTemplateSerializer


class EmailTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = EmailTemplateSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "subject"]
    ordering_fields = ["created_at", "name"]

    def get_queryset(self):
        return EmailTemplate.objects.filter(created_by=self.request.user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        template = self.get_object()
        return Response({"subject": template.subject, "html_content": template.html_content})

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        template = self.get_object()
        clone = EmailTemplate.objects.create(
            name=f"{template.name} (Copy)",
            subject=template.subject,
            html_content=template.html_content,
            created_by=request.user,
        )
        return Response(EmailTemplateSerializer(clone).data, status=status.HTTP_201_CREATED)
