from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import TimeStampedModel


class WorkspaceGroup(TimeStampedModel):
    name = models.CharField(
        max_length=150,
        verbose_name="Nombre del grupo"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )
    color = models.CharField(
        max_length=30,
        blank=True,
        default="gray",
        verbose_name="Color"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_workspace_groups",
        verbose_name="Creado por"
    )

    class Meta:
        verbose_name = "Grupo de trabajo"
        verbose_name_plural = "Grupos de trabajo"
        ordering = ["name"]

    def __str__(self):
        return self.name


class WorkspaceMembership(TimeStampedModel):
    ROLE_CHOICES = [
        ("owner", "Responsable"),
        ("coordinator", "Coordinador"),
        ("member", "Miembro"),
        ("viewer", "Observador"),
    ]

    group = models.ForeignKey(
        WorkspaceGroup,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name="Grupo"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
        verbose_name="Usuario"
    )
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default="member",
        verbose_name="Rol en el grupo"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Activo"
    )

    class Meta:
        verbose_name = "Miembro de grupo"
        verbose_name_plural = "Miembros de grupos"
        unique_together = ("group", "user")
        ordering = ["group__name", "user__username"]

    def __str__(self):
        return f"{self.user} - {self.group}"


class Task(TimeStampedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("in_progress", "En proceso"),
        ("waiting", "En espera"),
        ("completed", "Completada"),
        ("cancelled", "Cancelada"),
    ]

    PRIORITY_CHOICES = [
        ("low", "Baja"),
        ("medium", "Media"),
        ("high", "Alta"),
        ("urgent", "Urgente"),
    ]

    TASK_TYPE_CHOICES = [
        ("general", "General"),
        ("customer_request", "Solicitud de cliente"),
        ("catalog", "Catálogo"),
        ("price", "Precio"),
        ("publisher", "Editorial / Proveedor"),
        ("reading_plan", "Plan lector"),
        ("school", "Colegio"),
        ("delivery", "Entrega"),
        ("meeting", "Reunión"),
        ("call", "Llamada"),
        ("school_campaign", "Campaña escolar"),
        ("administration", "Administración"),
        ("warehouse", "Almacén"),
        ("other", "Otro"),
    ]

    title = models.CharField(
        max_length=180,
        verbose_name="Título"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )
    task_type = models.CharField(
        max_length=40,
        choices=TASK_TYPE_CHOICES,
        default="general",
        verbose_name="Tipo"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="Estado"
    )
    priority = models.CharField(
        max_length=30,
        choices=PRIORITY_CHOICES,
        default="medium",
        verbose_name="Prioridad"
    )
    group = models.ForeignKey(
        WorkspaceGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        verbose_name="Grupo de trabajo"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
        verbose_name="Creado por"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        verbose_name="Responsable"
    )
    start_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Inicio"
    )
    due_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha límite"
    )
    reminder_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Recordatorio"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de finalización"
    )
    is_important = models.BooleanField(
        default=False,
        verbose_name="Importante"
    )
    is_private = models.BooleanField(
        default=False,
        verbose_name="Privada"
    )
    related_contact_request = models.ForeignKey(
        "inquiries.ContactRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="related_tasks",
        verbose_name="Solicitud relacionada"
    )

    class Meta:
        verbose_name = "Tarea"
        verbose_name_plural = "Tareas"
        ordering = ["status", "due_at", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        if not self.due_at:
            return False

        if self.status in ["completed", "cancelled"]:
            return False

        return self.due_at < timezone.now()

    def mark_completed(self):
        self.status = "completed"
        self.completed_at = timezone.now()


class TaskComment(TimeStampedModel):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Tarea"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_comments",
        verbose_name="Usuario"
    )
    comment = models.TextField(
        verbose_name="Comentario / evidencia"
    )

    class Meta:
        verbose_name = "Comentario de tarea"
        verbose_name_plural = "Comentarios de tareas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.task} - {self.user}"


class TaskStatusHistory(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Tarea"
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_status_changes",
        verbose_name="Usuario"
    )
    old_status = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Estado anterior"
    )
    new_status = models.CharField(
        max_length=30,
        verbose_name="Estado nuevo"
    )
    note = models.TextField(
        blank=True,
        verbose_name="Nota"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Fecha de cambio"
    )

    class Meta:
        verbose_name = "Historial de estado de tarea"
        verbose_name_plural = "Historial de estados de tareas"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.old_status} → {self.new_status}"


class CalendarEvent(TimeStampedModel):
    EVENT_TYPE_CHOICES = [
        ("meeting", "Reunión"),
        ("call", "Llamada"),
        ("visit", "Visita"),
        ("training", "Capacitación"),
        ("delivery", "Entrega"),
        ("deadline", "Fecha límite"),
        ("internal", "Interno"),
        ("other", "Otro"),
    ]

    title = models.CharField(
        max_length=180,
        verbose_name="Título"
    )
    description = models.TextField(
        blank=True,
        verbose_name="Descripción"
    )
    event_type = models.CharField(
        max_length=30,
        choices=EVENT_TYPE_CHOICES,
        default="meeting",
        verbose_name="Tipo de evento"
    )
    group = models.ForeignKey(
        WorkspaceGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Grupo de trabajo"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_calendar_events",
        verbose_name="Creado por"
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_calendar_events",
        verbose_name="Responsable"
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="calendar_event_participations",
        verbose_name="Participantes"
    )
    start_at = models.DateTimeField(
        verbose_name="Inicio"
    )
    end_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fin"
    )
    is_all_day = models.BooleanField(
        default=False,
        verbose_name="Todo el día"
    )
    location = models.CharField(
        max_length=180,
        blank=True,
        verbose_name="Lugar"
    )
    related_task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="related_events",
        verbose_name="Tarea relacionada"
    )
    related_contact_request = models.ForeignKey(
        "inquiries.ContactRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="related_calendar_events",
        verbose_name="Solicitud relacionada"
    )

    class Meta:
        verbose_name = "Evento de calendario"
        verbose_name_plural = "Eventos de calendario"
        ordering = ["start_at"]

    def __str__(self):
        return self.title


class Reminder(TimeStampedModel):
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("seen", "Visto"),
        ("dismissed", "Descartado"),
        ("completed", "Completado"),
    ]

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_reminders",
        verbose_name="Creado por"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reminders",
        verbose_name="Responsable"
    )
    group = models.ForeignKey(
        WorkspaceGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reminders",
        verbose_name="Grupo de trabajo"
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
        verbose_name="Tarea"
    )
    event = models.ForeignKey(
        CalendarEvent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
        verbose_name="Evento"
    )
    title = models.CharField(
        max_length=180,
        verbose_name="Título"
    )
    message = models.TextField(
        blank=True,
        verbose_name="Mensaje"
    )
    remind_at = models.DateTimeField(
        verbose_name="Fecha de recordatorio"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="Estado"
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de finalización"
    )

    class Meta:
        verbose_name = "Recordatorio"
        verbose_name_plural = "Recordatorios"
        ordering = ["status", "remind_at"]

    def __str__(self):
        return self.title

    @property
    def is_completed(self):
        return self.status == "completed"

    @property
    def is_overdue(self):
        if self.status == "completed":
            return False

        return self.remind_at < timezone.now()

    def mark_completed(self):
        self.status = "completed"
        self.completed_at = timezone.now()

    def reopen(self):
        self.status = "pending"
        self.completed_at = None