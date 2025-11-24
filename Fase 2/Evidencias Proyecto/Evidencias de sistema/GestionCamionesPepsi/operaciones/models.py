from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.utils import timezone 

# 1. Modelo de Usuario con Roles 
class Usuario(AbstractUser):
    class Roles(models.TextChoices):
        COORDINACION = 'COORDINACION', 'Coordinación'
        SUPERVISOR = 'SUPERVISOR', 'Supervisor'
        MECANICO = 'MECANICO', 'Mecánico'
        CHOFER = 'CHOFER', 'Chofer'
        GUARDIA = 'GUARDIA', 'Guardia'
        JEFE_TALLER = 'JEFE_TALLER', 'Jefe de Taller'

    class Especialidades(models.TextChoices):
        GENERAL = 'GENERAL', 'General / Multiservicio'
        MOTOR = 'MOTOR', 'Motor y transmisión'
        ELECTRICIDAD = 'ELECTRICIDAD', 'Electricidad automotriz'
        FRENOS = 'FRENOS', 'Frenos y suspensión'
        AIRE = 'AIRE', 'Aire acondicionado y climatización'
        CARROCERIA = 'CARROCERIA', 'Carrocería y pintura'
        LLANTAS = 'LLANTAS', 'Llantas y alineación'
        DIAGNOSTICO = 'DIAGNOSTICO', 'Diagnóstico computarizado'

    rol = models.CharField(max_length=50, choices=Roles.choices)
    especialidad = models.CharField(
        max_length=50,
        choices=Especialidades.choices,
        blank=True, null=True,
        help_text="Especialidad del mecánico (seleccione una opción o 'General')."
    )

    @property
    def display_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.username

    def __str__(self):
        return f"{self.get_rol_display()}: {self.first_name} {self.last_name} ({self.username})"

# 2. Modelo Sitio 
class Sitio(models.Model):
    nombre_sitio = models.CharField(max_length=100, unique=True)
    
    def __str__(self):
        return self.nombre_sitio

# 3. Modelo Taller 
class Taller(models.Model):
    nombre_taller = models.CharField(max_length=100)
    ubicacion = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.nombre_taller

# 4. Modelo de Vehículo
class Vehiculo(models.Model):
    class EstadoVehiculo(models.TextChoices): 
        ASIGNADO = 'ASIGNADO', 'Asignado (Pendiente Salida)'
        DISPONIBLE = 'DISPONIBLE', 'Disponible'
        EN_TALLER = 'EN_TALLER', 'En Taller'
        EN_RUTA = 'EN_RUTA', 'En Ruta'
        DE_BAJA = 'DE_BAJA', 'De Baja'

    patente = models.CharField(max_length=10, unique=True, primary_key=True)
    marca = models.CharField(max_length=50)
    modelo = models.CharField(max_length=50)
    año = models.PositiveIntegerField()
    chofer_asignado = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        limit_choices_to={'rol': Usuario.Roles.CHOFER},
        related_name="vehiculos"
    )
    
    sitio = models.ForeignKey(Sitio, on_delete=models.PROTECT, null=True, related_name="vehiculos") 
    es_backup = models.BooleanField(default=False, help_text="Marcar si es un vehículo de respaldo.") 
    estado_actual = models.CharField(max_length=50, choices=EstadoVehiculo.choices, default=EstadoVehiculo.DISPONIBLE) 

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.patente})"

# 5. Modelo de Mantenimiento
class Mantenimiento(models.Model):
    class Estado(models.TextChoices):
        SOLICITADO = 'SOLICITADO', 'Solicitado'
        AGENDADO = 'AGENDADO', 'Agendado'
        EN_TALLER = 'EN_TALLER', 'En Taller'
        DIAGNOSTICO = 'DIAGNOSTICO', 'Diagnóstico'
        EN_REPARACION = 'EN_REPARACION', 'En Reparación'
        REPARADO = 'REPARADO', 'Reparado'
        VALIDADO = 'VALIDADO', 'Validado' 
        FINALIZADO = 'FINALIZADO', 'Finalizado'
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name="mantenimientos")
    mecanico_asignado = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={'rol': Usuario.Roles.MECANICO},
        related_name="mantenimientos_asignados"
    )
    
    # Tiempos y estados 
    fecha_solicitud = models.DateTimeField(default=timezone.now)
    fecha_hora_llegada = models.DateTimeField(null=True, blank=True, help_text="Fecha y hora de ingreso real al taller (registra Guardia)") 
    fecha_salida_estimada = models.DateTimeField(null=True, blank=True)
    fecha_salida_real = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=50, choices=Estado.choices, default=Estado.SOLICITADO)
    
    taller = models.ForeignKey(Taller, on_delete=models.SET_NULL, null=True, blank=True)

    # Descripción del trabajo
    motivo_ingreso = models.TextField(help_text="Descripción inicial del problema por el chofer.")
    diagnostico = models.TextField(blank=True, help_text="Análisis técnico del mecánico.")
    trabajo_realizado = models.TextField(blank=True, help_text="Descripción de las reparaciones efectuadas.")
    
    # Trazabilidad y validación 
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        limit_choices_to={'rol': Usuario.Roles.CHOFER},
        related_name='solicitudes_mantenimiento'
    )
    validado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={'rol': Usuario.Roles.SUPERVISOR},
        related_name="reparaciones_validadas"
    )
    fecha_validacion = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Mantenimiento para {self.vehiculo.patente} - {self.get_estado_display()}"

# 6. Modelo de Documentos Legales
class Documento(models.Model):
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='documentos')
    nombre_documento = models.CharField(max_length=100) # Ej: "Seguro", "Padrón", etc.
    archivo = models.FileField(upload_to='documentos_vehiculos/')
    fecha_vencimiento = models.DateField(null=True, blank=True)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nombre_documento} de {self.vehiculo.patente}"

# 7. Modelo para Fotos de Evidencia del Mantenimiento
class FotoMantenimiento(models.Model):
    mantenimiento = models.ForeignKey(Mantenimiento, on_delete=models.CASCADE, related_name='fotos')
    imagen = models.ImageField(upload_to='fotos_mantenimiento/')
    descripcion = models.CharField(max_length=255, blank=True)
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha_carga = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Foto para mantenimiento de {self.mantenimiento.vehiculo.patente}"

# 8. Modelo para Observaciones y Bitácora
class Observacion(models.Model):
    mantenimiento = models.ForeignKey(Mantenimiento, on_delete=models.CASCADE, related_name='observaciones')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    texto = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha'] 

    def __str__(self):
        return f"Obs. de {self.usuario.username} en {self.mantenimiento.vehiculo.patente}"

# 9. Modelo para Pausas de Trabajo
class Pausa(models.Model):
    mantenimiento = models.ForeignKey(Mantenimiento, on_delete=models.CASCADE, related_name='pausas')
    mecanico = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        limit_choices_to={'rol': Usuario.Roles.MECANICO}
    )
    inicio_pausa = models.DateTimeField(auto_now_add=True)
    fin_pausa = models.DateTimeField(null=True, blank=True)
    motivo = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"Pausa de {self.mecanico.username} en mant. de {self.mantenimiento.vehiculo.patente}"

# 10. Modelo Agenda Taller 
class Agenda_Taller(models.Model):
    class TipoAtencion(models.TextChoices):
        RUTINA = 'RUTINA', 'Revisión de Rutina'
        MECANICA = 'MECANICA', 'Mecánica'
        ELECTRICIDAD = 'ELECTRICIDAD', 'Electricidad'
        DOCUMENTACION = 'DOCUMENTACION', 'Documentación'

    taller = models.ForeignKey(Taller, on_delete=models.CASCADE, related_name='agenda')
    mantenimiento = models.OneToOneField(Mantenimiento, on_delete=models.CASCADE, null=True, blank=True, related_name='agenda')
    tipo_atencion = models.CharField(max_length=50, choices=TipoAtencion.choices)
    hora_inicio = models.DateTimeField()
    hora_final = models.DateTimeField()
    
    class Meta:
        ordering = ['hora_inicio']
        verbose_name = "Bloque de Agenda"
        verbose_name_plural = "Agenda del Taller"

    def __str__(self):
        return f"{self.get_tipo_atencion_display()} en {self.taller.nombre_taller} ({self.hora_inicio.strftime('%d/%m %H:%M')})"

# 11. Modelo Insumo 
class Insumo(models.Model):
    class EstadoAprobacion(models.TextChoices): 
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        APROBADO = 'APROBADO', 'Aprobado'
        RECHAZADO = 'RECHAZADO', 'Rechazado'

    mantenimiento = models.ForeignKey(Mantenimiento, on_delete=models.CASCADE, related_name='insumos')
    nombre_insumo = models.CharField(max_length=100)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True) 
    fecha_solicitud = models.DateTimeField(default=timezone.now) 
    estado_aprobacion = models.CharField(max_length=50, choices=EstadoAprobacion.choices, default=EstadoAprobacion.PENDIENTE) 
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='insumos_aprobados') 
    fecha_aprobacion = models.DateTimeField(null=True, blank=True) 

    def __str__(self):
        return f"{self.cantidad} x {self.nombre_insumo} para {self.mantenimiento.vehiculo.patente}"

# 12. Modelo Historial Cambios 
class Historial_Cambios(models.Model):
    class TipoCambio(models.TextChoices):
        CREACION = 'CREACION', 'Creación'
        EDICION = 'EDICION', 'Edición'
        ELIMINACION = 'ELIMINACION', 'Eliminación'
        LOGIN = 'LOGIN', 'Inicio Sesión'
        ACCESO = 'ACCESO', 'Acceso'

    fecha_cambio = models.DateTimeField(auto_now_add=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    tipo_cambio = models.CharField(max_length=50, choices=TipoCambio.choices)
    tabla_afectada = models.CharField(max_length=100, blank=True)
    id_registro_afectado = models.CharField(max_length=50, blank=True)
    descripcion = models.TextField(help_text="Descripción del cambio realizado")

    class Meta:
        ordering = ['-fecha_cambio']
        verbose_name = "Registro de Auditoría"
        verbose_name_plural = "Registros de Auditoría"

    def __str__(self):
        return f"[{self.fecha_cambio.strftime('%d/%m %H:%M')}] {self.usuario}: {self.get_tipo_cambio_display()} en {self.tabla_afectada}"

# 13. Modelo para Solicitudes de Vehículos de Respaldo
class SolicitudBackup(models.Model):
    class EstadoSolicitud(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        ATENDIDA = 'ATENDIDA', 'Atendida'
        CANCELADA = 'CANCELADA', 'Cancelada'

    chofer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='solicitudes_backup')
    motivo = models.TextField(blank=True)
    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=50, choices=EstadoSolicitud.choices, default=EstadoSolicitud.PENDIENTE)
    
    # Campos para trazabilidad
    atendido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='solicitudes_atendidas')
    fecha_atencion = models.DateTimeField(null=True, blank=True)
    vehiculo_asignado = models.ForeignKey(Vehiculo, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-fecha_solicitud']
        verbose_name = "Solicitud de Backup"
        verbose_name_plural = "Solicitudes de Backup"

    def __str__(self):
        return f"Solicitud de {self.chofer.display_name} el {self.fecha_solicitud.strftime('%d/%m/%Y')}"