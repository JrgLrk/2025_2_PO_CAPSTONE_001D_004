
from django.shortcuts import render, redirect, get_object_or_404
from django import forms
from django.utils import timezone
from django.urls import reverse_lazy
from datetime import timedelta, datetime
from django.contrib.auth.decorators import login_required
from .models import Vehiculo, Mantenimiento, Usuario, Agenda_Taller, Documento, Historial_Cambios, Insumo, FotoMantenimiento, Pausa, Sitio, SolicitudBackup, Taller, Observacion
from .forms import MantenimientoSolicitudForm, DiagnosticoForm, InsumoForm, FotoMantenimientoForm, PausaForm, DocumentoForm, CustomUserCreationForm, CustomUserChangeForm, VehiculoForm, SitioForm, GeneradorAgendaForm, EliminadorAgendaForm, AsignarBackupForm
from django.contrib import messages
from .decorators import role_required
from django.db.models import Case, When, Value
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
import json, io
import pandas as pd
from django.db.models import Count, Avg, F
import csv

@login_required
def home(request):
    """
    Redirige al usuario a su dashboard correspondiente según su rol.
    Si no tiene un rol específico, muestra una página por defecto.
    """
    if request.user.rol == Usuario.Roles.CHOFER:
        return redirect('chofer_dashboard')
    if request.user.rol == Usuario.Roles.MECANICO:
        return redirect('mecanico_dashboard')
    if request.user.rol == Usuario.Roles.GUARDIA:
        return redirect('guardia_dashboard')
    if request.user.rol == Usuario.Roles.SUPERVISOR:
        return redirect('supervisor_dashboard')
    if request.user.rol == Usuario.Roles.JEFE_TALLER:
        return redirect('jefe_taller_dashboard')
    if request.user.rol == Usuario.Roles.COORDINACION:
        return redirect('coordinacion_dashboard')
    
    return render(request, 'default.html')


# --- Vistas CHOFER ---
@login_required
@role_required(allowed_roles=[Usuario.Roles.CHOFER])
def chofer_dashboard(request):
    """
    Panel principal para el rol de Chofer.
    Muestra sus vehículos, notificaciones importantes sobre backups y el estado
    de sus mantenimientos activos.
    """
    # Obtenemos todos los vehículos, tanto principales como de respaldo, que el chofer tiene asignados.
    vehiculos_asignados = Vehiculo.objects.filter(
        chofer_asignado=request.user
    ).order_by('patente')

    # Vehículos principales y backup
    vehiculos_principales = vehiculos_asignados.filter(es_backup=False)
    vehiculos_backup = vehiculos_asignados.filter(es_backup=True)
    
    # El vehículo principal del chofer, incluso si está en taller
    vehiculo_principal = vehiculos_asignados.filter(es_backup=False).first()
    
    # Notificación 1: Backup asignado pendiente de retiro
    backup_por_retirar = vehiculos_asignados.filter(
        es_backup=True,
        estado_actual=Vehiculo.EstadoVehiculo.ASIGNADO
    ).first()
    if backup_por_retirar:
        mensaje = (f"**Vehículo de Respaldo Asignado:** Se te ha asignado el vehículo de respaldo con patente "
                   f"**{backup_por_retirar.patente}**. Por favor, dirígete al recinto para retirarlo.")
        messages.info(request, mensaje)

    # Si el chofer está usando un backup, verificamos si su vehículo principal ya está listo.
    backup_en_uso = vehiculos_asignados.filter(
        es_backup=True,
        estado_actual=Vehiculo.EstadoVehiculo.EN_RUTA
    ).first()

    mantenimiento_listo = None
    if backup_en_uso:
        # Si el vehículo principal está listo (VALIDADO), notificamos para devolver el backup.
        mantenimiento_listo = Mantenimiento.objects.filter( 
            vehiculo=vehiculo_principal, estado=Mantenimiento.Estado.VALIDADO
        ).first()

        if mantenimiento_listo:
            mensaje = (f"**¡Atención!** Tu vehículo principal ({mantenimiento_listo.vehiculo.patente}) está listo. "
                       f"Por favor, coordina la devolución del vehículo de respaldo ({backup_en_uso.patente}).")
            messages.warning(request, mensaje)

    # Mantenimientos activos para el chofer
    mantenimientos_activos = Mantenimiento.objects.filter(
        vehiculo=vehiculo_principal,
        estado__in=[
            Mantenimiento.Estado.AGENDADO,
            Mantenimiento.Estado.EN_TALLER,
            Mantenimiento.Estado.DIAGNOSTICO,
            Mantenimiento.Estado.EN_REPARACION,
            Mantenimiento.Estado.REPARADO,
            Mantenimiento.Estado.VALIDADO,
        ]
    ).order_by('-fecha_solicitud').first()

    # El mantenimiento a mostrar en el dashboard es el activo.
    # Si hay uno validado, ese tiene prioridad para mostrar el botón de confirmación.
    mantenimiento_actual = Mantenimiento.objects.filter(
        vehiculo=vehiculo_principal
    ).exclude(
        estado=Mantenimiento.Estado.FINALIZADO
    ).select_related(
        'taller', 'vehiculo__sitio'
    ).order_by('-fecha_solicitud').first()
    
    # Si el mantenimiento está validado, mostramos un mensaje de éxito.
    if mantenimiento_actual and mantenimiento_actual.estado == Mantenimiento.Estado.VALIDADO:
        info_taller = f" en el taller '{mantenimiento_actual.taller.nombre_taller}'" if mantenimiento_actual.taller else ""
        mensaje = (f"**¡Vehículo Listo!** Tu vehículo principal ({mantenimiento_actual.vehiculo.patente}) está listo para ser retirado. "
                   f"El guardia registrará la salida.")
        messages.success(request, mensaje)

    # Contexto final unificado
    context = {
        'vehiculos_principales': vehiculos_principales,
        'vehiculos_backup': vehiculos_backup,
        'mantenimiento_actual': mantenimiento_actual,
        'ultimo_mantenimiento': Mantenimiento.objects.filter(
            solicitado_por=request.user
        ).order_by('-fecha_solicitud').first(),
    }

    return render(request, 'chofer/dashboard.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.CHOFER])
def solicitar_atencion(request):
    """
    Permite al chofer solicitar una cita de mantenimiento.
    Muestra los horarios disponibles y procesa la selección, creando un nuevo
    registro de Mantenimiento y asociándolo a un slot de la agenda.
    """
    if request.method == 'POST':
        form = MantenimientoSolicitudForm(request.POST, user=request.user)
        if form.is_valid():
            slot_id = form.cleaned_data['agenda_slot']
            try:
                agenda_slot = Agenda_Taller.objects.get(id=slot_id)
            except Agenda_Taller.DoesNotExist:
                messages.error(request, "El horario seleccionado no es válido.")
                return redirect('solicitar_atencion')

            # Verificamos que el horario no haya sido tomado por otro usuario mientras el chofer decidía.
            if agenda_slot.mantenimiento is not None:
                messages.warning(request, "Ese horario ya fue tomado. Elija otro.")
                return redirect('solicitar_atencion')

            # Creamos el mantenimiento con estado 'AGENDADO'.
            mantenimiento = form.save(commit=False)
            mantenimiento.solicitado_por = request.user
            mantenimiento.estado = Mantenimiento.Estado.AGENDADO
            mantenimiento.taller = agenda_slot.taller
            mantenimiento.save()

            # "Reservamos" el slot de la agenda, vinculándolo al mantenimiento recién creado.
            agenda_slot.mantenimiento = mantenimiento
            agenda_slot.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.CREACION,
                tabla_afectada="Mantenimiento",
                id_registro_afectado=mantenimiento.id,
                descripcion=f"Chofer solicitó mantenimiento para el {agenda_slot.hora_inicio.strftime('%d/%m')}"
            )

            messages.success(request, f"Cita agendada para la patente {mantenimiento.vehiculo.patente}.")
            return redirect('chofer_dashboard')
    else:
        form = MantenimientoSolicitudForm(user=request.user)

    # Para el método GET, filtramos y mostramos solo los slots futuros que estén libres.
    slots_disponibles = Agenda_Taller.objects.filter(
        mantenimiento__isnull=True,
        hora_inicio__gte=timezone.now()
    ).order_by('hora_inicio')

    context = {'form': form, 'slots_disponibles': slots_disponibles}
    return render(request, 'chofer/solicitar_atencion.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.CHOFER])
def ver_documentos(request):
    """
    Muestra al chofer una lista de todos los documentos asociados a sus vehículos.
    """
    vehiculos_del_chofer = Vehiculo.objects.filter(chofer_asignado=request.user)
    documentos = Documento.objects.filter(
        vehiculo__in=vehiculos_del_chofer
    ).order_by('vehiculo__patente', 'nombre_documento')

    context = {'vehiculos': vehiculos_del_chofer, 'documentos': documentos}
    return render(request, 'chofer/ver_documentos.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.CHOFER])
def ver_backups(request):
    """
    Permite al chofer enviar una solicitud formal para un vehículo de respaldo.
    Evita que se creen solicitudes duplicadas si ya existe una pendiente.
    """
    # Verificamos si ya hay una solicitud en curso para evitar duplicados.
    solicitud_existente = SolicitudBackup.objects.filter(chofer=request.user, estado=SolicitudBackup.EstadoSolicitud.PENDIENTE).exists()

    if request.method == 'POST':
        if solicitud_existente:
            messages.warning(request, "Ya tienes una solicitud de respaldo pendiente.")
            return redirect('chofer_dashboard')

        motivo = request.POST.get('motivo', 'Motivo no especificado.')
        SolicitudBackup.objects.create(chofer=request.user, motivo=motivo)
        messages.info(request, "Tu solicitud de vehículo de respaldo ha sido enviada al coordinador. Serás notificado cuando se te asigne uno.")
        return redirect('chofer_dashboard')

    context = {'solicitud_existente': solicitud_existente}
    return render(request, 'chofer/solicitar_backup.html', context)

@login_required
def descargar_documento(request, documento_id):
    """
    Entrega un archivo de documento de forma segura, verificando los permisos del usuario.
    - Supervisores y Coordinadores pueden descargar cualquier documento.
    - Choferes solo pueden descargar documentos de sus vehículos asignados.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    user = request.user

    # Permitir acceso a roles de gestión
    if user.rol in [Usuario.Roles.SUPERVISOR, Usuario.Roles.COORDINACION]:
        pass  # Tienen permiso para ver todo
    # Permitir a choferes ver solo documentos de sus vehículos
    elif user.rol == Usuario.Roles.CHOFER:
        vehiculos_del_chofer = Vehiculo.objects.filter(chofer_asignado=user).values_list('patente', flat=True)
        if documento.vehiculo.patente not in vehiculos_del_chofer:
            raise Http404("No tiene permiso para acceder a este documento.")
    else:
        # Otros roles no tienen acceso
        raise Http404("Acceso denegado.")

    try:
        return FileResponse(documento.archivo.open('rb'), as_attachment=True, filename=documento.archivo.name)
    except FileNotFoundError:
        raise Http404("Archivo no encontrado.")

@login_required
def descargar_foto_mantenimiento(request, foto_id):
    foto = get_object_or_404(FotoMantenimiento, id=foto_id)
    mantenimiento = foto.mantenimiento
    if not (request.user.rol in [Usuario.Roles.SUPERVISOR, Usuario.Roles.COORDINACION] or request.user == mantenimiento.mecanico_asignado):
        raise Http404("No tiene permiso para ver esta foto.")
    return FileResponse(foto.imagen.open('rb'), as_attachment=False, filename=foto.imagen.name)

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def coordinacion_dashboard(request):
    """
    Panel principal para el rol de Coordinación.
    """
    # Contamos las solicitudes pendientes para mostrar notificaciones en el panel.
    pending_backups_count = SolicitudBackup.objects.filter(estado=SolicitudBackup.EstadoSolicitud.PENDIENTE).count()
    pending_insumos_count = Insumo.objects.filter(estado_aprobacion=Insumo.EstadoAprobacion.PENDIENTE).count()

    context = {
        'pending_backups_count': pending_backups_count,
        'pending_insumos_count': pending_insumos_count,
    }
    return render(request, 'coordinacion/coordinacion.html', context)

#Vistas de Gestión para Coordinación

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def gestion_agenda(request):
    """
    Vista central para la gestión de la agenda de talleres. Permite:
    - Generar nuevos horarios (slots o bloques).
    - Eliminar horarios disponibles en masa.
    - Eliminar un horario específico.
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'generar_agenda':
            form = GeneradorAgendaForm(request.POST)
            if form.is_valid():
                data = form.cleaned_data
                slots_a_crear = []
                fecha_actual = data['fecha_inicio']
                
                while fecha_actual <= data['fecha_fin']:
                    if str(fecha_actual.weekday()) in data['dias_semana']:
                        hora_apertura_dt = datetime.combine(fecha_actual, data['hora_apertura'])
                        hora_cierre_dt = datetime.combine(fecha_actual, data['hora_cierre'])
                        
                        # Modo 1: Genera múltiples slots de una duración fija (ej: cada 60 minutos).
                        if data['modo_generacion'] == 'slots':
                            if not data.get('duracion_slot'):
                                messages.error(request, "Debe especificar la duración del slot para este modo.")
                                return redirect('gestion_agenda')

                            hora_actual_slot = hora_apertura_dt
                            while hora_actual_slot < hora_cierre_dt:
                                hora_fin_slot = hora_actual_slot + timedelta(minutes=data['duracion_slot'])
                                if hora_fin_slot > hora_cierre_dt:
                                    break
                                
                                # Si un slot se superpone con el horario de colación, lo saltamos.
                                if data.get('hora_inicio_colacion'):
                                    h_inicio_col = datetime.combine(fecha_actual, data['hora_inicio_colacion'])
                                    h_fin_col = h_inicio_col + timedelta(minutes=data['duracion_colacion'])
                                    if hora_actual_slot < h_fin_col and hora_fin_slot > h_inicio_col:
                                        hora_actual_slot = h_fin_col
                                        continue

                                slots_a_crear.append(
                                    Agenda_Taller(taller=data['taller'], tipo_atencion=data['tipo_atencion'], hora_inicio=hora_actual_slot, hora_final=hora_fin_slot)
                                )
                                hora_actual_slot = hora_fin_slot

                        # Modo 2: Genera un bloque para la mañana y otro para la tarde, divididos por la colación.
                        elif data['modo_generacion'] == 'bloques':
                            if data.get('hora_inicio_colacion'):
                                h_inicio_col = datetime.combine(fecha_actual, data['hora_inicio_colacion'])
                                h_fin_col = h_inicio_col + timedelta(minutes=data['duracion_colacion'])
                                # Bloque mañana
                                if hora_apertura_dt < h_inicio_col:
                                    slots_a_crear.append(Agenda_Taller(taller=data['taller'], tipo_atencion=data['tipo_atencion'], hora_inicio=hora_apertura_dt, hora_final=h_inicio_col))
                                # Bloque tarde
                                if h_fin_col < hora_cierre_dt:
                                    slots_a_crear.append(Agenda_Taller(taller=data['taller'], tipo_atencion=data['tipo_atencion'], hora_inicio=h_fin_col, hora_final=hora_cierre_dt))
                            else: # Sin colación, un solo bloque
                                slots_a_crear.append(Agenda_Taller(taller=data['taller'], tipo_atencion=data['tipo_atencion'], hora_inicio=hora_apertura_dt, hora_final=hora_cierre_dt))

                    fecha_actual += timedelta(days=1)

                if slots_a_crear:
                    Agenda_Taller.objects.bulk_create(slots_a_crear)
                    messages.success(request, f"¡Éxito! Se han creado {len(slots_a_crear)} nuevos horarios en la agenda.")
                else:
                    messages.warning(request, "No se generaron horarios con los criterios seleccionados.")
            else:
                messages.error(request, "Hubo un error en el formulario de generación. Por favor, revisa los datos.")

        elif action == 'eliminar_agenda':
            delete_form = EliminadorAgendaForm(request.POST)
            if delete_form.is_valid():
                data = delete_form.cleaned_data
                
                # Buscamos todos los slots que no estén reservados en el rango de fechas.
                slots_query = Agenda_Taller.objects.filter(
                    taller=data['taller'],
                    hora_inicio__date__range=(data['fecha_inicio'], data['fecha_fin']),
                    mantenimiento__isnull=True
                )

                tipo_atencion = data.get('tipo_atencion')
                if tipo_atencion:
                    slots_query = slots_query.filter(tipo_atencion=tipo_atencion)

                count = slots_query.count()
                slots_query.delete()

                Historial_Cambios.objects.create(
                    usuario=request.user, tipo_cambio=Historial_Cambios.TipoCambio.ELIMINACION,
                    tabla_afectada="Agenda_Taller",
                    descripcion=f"Se eliminaron {count} slots de agenda del taller '{data['taller']}' entre {data['fecha_inicio']} y {data['fecha_fin']}."
                )

                messages.warning(request, f"Se han eliminado {count} horarios de la especialidad seleccionada en el rango de fechas.")
            else:
                messages.error(request, "Hubo un error en el formulario de eliminación.")

        elif action == 'eliminar_slot_especifico':
            slot_id = request.POST.get('slot_a_eliminar')
            if not slot_id:
                messages.error(request, "Debe seleccionar un horario para eliminar.")
            else:
                try:
                    slot = Agenda_Taller.objects.get(id=slot_id, mantenimiento__isnull=True)
                    descripcion_slot = str(slot) # Guardamos una descripción para el mensaje.
                    slot.delete()
                    
                    Historial_Cambios.objects.create(
                        usuario=request.user, tipo_cambio=Historial_Cambios.TipoCambio.ELIMINACION,
                        tabla_afectada="Agenda_Taller", id_registro_afectado=slot_id,
                        descripcion=f"Se eliminó el slot específico: {descripcion_slot}."
                    )
                    messages.warning(request, f"Se ha eliminado el horario: {descripcion_slot}.")
                except Agenda_Taller.DoesNotExist:
                    messages.error(request, "El horario seleccionado no existe o ya fue reservado.")

        return redirect('gestion_agenda')

    else: # Método GET
        generador_form = GeneradorAgendaForm()
        eliminador_form = EliminadorAgendaForm()

    # Lógica para el Calendario
    eventos_agenda = Agenda_Taller.objects.select_related('mantenimiento__vehiculo').all()
    calendar_events = []
    for evento in eventos_agenda:
        if evento.mantenimiento:
            title = f"Ocupado: {evento.mantenimiento.vehiculo.patente}"
            backgroundColor = '#dc3545' # Rojo para ocupado
        else:
            title = "Disponible"
            backgroundColor = '#198754' # Verde para disponible
        
        calendar_events.append({
            'title': title,
            'start': evento.hora_inicio.isoformat(),
            'end': evento.hora_final.isoformat(),
            'backgroundColor': backgroundColor,
            'borderColor': backgroundColor,
            'textColor': 'white',
        })

    slots_eliminables = Agenda_Taller.objects.filter(
        mantenimiento__isnull=True
    ).select_related('taller').order_by('hora_inicio')

    context = {
        'form_generador': generador_form,
        'form_eliminador': eliminador_form,
        'calendar_events': json.dumps(calendar_events),
        'slots_eliminables': slots_eliminables,
    }
    return render(request, 'coordinacion/gestion_agenda.html', context)


from django.views.generic import ListView, CreateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin

class CoordinationRequiredMixin(UserPassesTestMixin):
    """Mixin para vistas basadas en clases que solo permite acceso a Coordinación."""
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.rol == Usuario.Roles.COORDINACION

#Gestión de Usuarios

class UserListView(LoginRequiredMixin, CoordinationRequiredMixin, ListView):
    """Muestra una lista de todos los usuarios, con filtros por rol y especialidad."""
    model = Usuario
    template_name = 'coordinacion/user_list.html'
    context_object_name = 'usuarios'

    def get_queryset(self):
        queryset = super().get_queryset().order_by('first_name')
        filtro_rol = self.request.GET.get('rol', '')
        filtro_especialidad = self.request.GET.get('especialidad', '')

        if filtro_rol:
            queryset = queryset.filter(rol=filtro_rol)
        if filtro_especialidad:
            queryset = queryset.filter(especialidad=filtro_especialidad)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['roles_posibles'] = Usuario.Roles.choices
        context['especialidades_posibles'] = Usuario.Especialidades.choices
        context['filtro_rol_actual'] = self.request.GET.get('rol', '')
        context['filtro_especialidad_actual'] = self.request.GET.get('especialidad', '')
        return context


user_list = UserListView.as_view()

class UserCreateView(LoginRequiredMixin, CoordinationRequiredMixin, CreateView):
    """Formulario para crear un nuevo usuario."""
    model = Usuario
    form_class = CustomUserCreationForm
    template_name = 'coordinacion/user_form.html'
    success_url = reverse_lazy('user_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Crear Nuevo Usuario'
        return context

user_create = UserCreateView.as_view()

class UserEditView(LoginRequiredMixin, CoordinationRequiredMixin, UpdateView):
    """Formulario para editar un usuario existente, incluyendo el cambio de contraseña."""
    model = Usuario
    form_class = CustomUserChangeForm
    template_name = 'coordinacion/user_form.html'
    success_url = reverse_lazy('user_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Editar Usuario'
        return context

    def form_valid(self, form):
        usuario = form.save(commit=False)
        
        # Si el coordinador ingresó una nueva contraseña, la actualizamos.
        new_password = form.cleaned_data.get('new_password1')
        if new_password:
            usuario.set_password(new_password)
        
        usuario.save()

        descripcion_historial = f"Coordinador actualizó datos del usuario {usuario.username}."
        if new_password:
            descripcion_historial += " Se cambió la contraseña."

        Historial_Cambios.objects.create(
            usuario=self.request.user, tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
            tabla_afectada="Usuario", id_registro_afectado=usuario.id,
            descripcion=descripcion_historial
        )
        messages.success(self.request, f"Usuario {usuario.username} actualizado correctamente.")
        return super().form_valid(form)

user_edit = UserEditView.as_view()

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def user_deactivate(request, pk):
    """
    Desactiva un usuario en lugar de eliminarlo, para mantener la integridad de los registros.
    """
    usuario = get_object_or_404(Usuario, pk=pk)
    if request.method == 'POST':
        usuario.is_active = False
        usuario.save()
        messages.warning(request, f"El usuario {usuario.username} ha sido desactivado.")
    return redirect('user_list')

# Gestión de Vehículos

class VehicleListView(LoginRequiredMixin, CoordinationRequiredMixin, ListView):
    """Muestra una lista de todos los vehículos, con filtros."""
    model = Vehiculo
    template_name = 'coordinacion/vehicle_list.html'
    context_object_name = 'vehiculos'

    def get_queryset(self):
        queryset = super().get_queryset().select_related('chofer_asignado', 'sitio').order_by('patente')
        filtro_patente = self.request.GET.get('patente', '').strip()
        filtro_sitio = self.request.GET.get('sitio', '')
        filtro_estado = self.request.GET.get('estado', '')

        if filtro_patente:
            queryset = queryset.filter(patente__icontains=filtro_patente)
        if filtro_sitio:
            queryset = queryset.filter(sitio_id=filtro_sitio)
        if filtro_estado:
            queryset = queryset.filter(estado_actual=filtro_estado)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sitios_posibles'] = Sitio.objects.all()
        context['estados_posibles'] = Vehiculo.EstadoVehiculo.choices
        context['filtro_patente_actual'] = self.request.GET.get('patente', '')
        context['filtro_sitio_actual'] = self.request.GET.get('sitio', '')
        context['filtro_estado_actual'] = self.request.GET.get('estado', '')
        return context

vehicle_list = VehicleListView.as_view()

class VehicleCreateView(LoginRequiredMixin, CoordinationRequiredMixin, CreateView):
    """Formulario para añadir un nuevo vehículo al sistema."""
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'coordinacion/vehicle_form.html'
    success_url = reverse_lazy('vehicle_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Añadir Nuevo Vehículo'
        return context

vehicle_create = VehicleCreateView.as_view()

class VehicleEditView(LoginRequiredMixin, CoordinationRequiredMixin, UpdateView):
    """Formulario para editar la información de un vehículo existente."""
    model = Vehiculo
    form_class = VehiculoForm
    template_name = 'coordinacion/vehicle_form.html'
    success_url = reverse_lazy('vehicle_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Editar Vehículo'
        return context

vehicle_edit = VehicleEditView.as_view()

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def vehicle_deactivate(request, pk):
    """
    Marca un vehículo como 'DE_BAJA' para sacarlo de circulación sin borrar su historial.
    """
    vehiculo = get_object_or_404(Vehiculo, pk=pk)
    if request.method == 'POST':
        vehiculo.estado_actual = Vehiculo.EstadoVehiculo.DE_BAJA
        vehiculo.chofer_asignado = None 
        vehiculo.save()
        messages.warning(request, f"El vehículo {vehiculo.patente} ha sido dado de baja y ya no está operativo.")
    return redirect('vehicle_list')

# Gestión de Sitios

class SitioListView(LoginRequiredMixin, CoordinationRequiredMixin, ListView):
    """Muestra una lista de todos los sitios o bases de operación."""
    model = Sitio
    template_name = 'coordinacion/sitio_list.html'
    context_object_name = 'sitios'

sitio_list = SitioListView.as_view()

class SitioCreateView(LoginRequiredMixin, CoordinationRequiredMixin, CreateView):
    """Formulario para crear un nuevo sitio."""
    model = Sitio
    form_class = SitioForm
    template_name = 'coordinacion/sitio_form.html'
    success_url = reverse_lazy('sitio_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Crear Nuevo Sitio'
        return context

sitio_create = SitioCreateView.as_view()

class SitioEditView(LoginRequiredMixin, CoordinationRequiredMixin, UpdateView):
    """Formulario para editar el nombre de un sitio existente."""
    model = Sitio
    form_class = SitioForm
    template_name = 'coordinacion/sitio_form.html'
    success_url = reverse_lazy('sitio_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['titulo'] = 'Editar Sitio'
        return context

sitio_edit = SitioEditView.as_view()


@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def sitio_delete(request, pk):
    """
    Elimina un sitio, solo si no tiene vehículos asociados.
    """
    sitio = get_object_or_404(Sitio, pk=pk)
    if request.method == 'POST':
        if sitio.vehiculos.exists():
            messages.error(request, f"No se puede eliminar el sitio '{sitio.nombre_sitio}' porque todavía tiene vehículos asignados.")
        else:
            sitio.delete()
            messages.warning(request, f"El sitio '{sitio.nombre_sitio}' ha sido eliminado correctamente.")
    return redirect('sitio_list')

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def gestion_backups(request):
    """
    Permite al Coordinador ver solicitudes pendientes y asignar vehículos de respaldo a los choferes.
    """
    if request.method == 'POST':
        form = AsignarBackupForm(request.POST)
        if form.is_valid():
            chofer_solicitante = form.cleaned_data['chofer']
            patente = form.cleaned_data['vehiculo_patente']
            solicitud_id = request.POST.get('solicitud_id') # Obtenemos el ID de la solicitud
            
            try:
                vehiculo = Vehiculo.objects.get(patente=patente, es_backup=True)

                # Verificamos que el chofer no tenga ya otro vehículo en uso.
                if Vehiculo.objects.filter(chofer_asignado=chofer_solicitante, estado_actual=Vehiculo.EstadoVehiculo.EN_RUTA).exists():
                    messages.error(request, f"No se puede asignar. El chofer {chofer_solicitante.get_full_name()} ya tiene un vehículo en ruta.")
                else:
                    vehiculo_principal = Vehiculo.objects.filter(chofer_asignado=chofer_solicitante, es_backup=False).first()

                    if not vehiculo_principal or vehiculo_principal.estado_actual == Vehiculo.EstadoVehiculo.EN_TALLER:
                        vehiculo.chofer_asignado = chofer_solicitante 
                        vehiculo.estado_actual = Vehiculo.EstadoVehiculo.ASIGNADO
                        vehiculo.save()
                        messages.success(request, f"Vehículo de respaldo {patente} asignado a {chofer_solicitante.get_full_name()}.")

                        # Si la asignación viene de una solicitud, la marcamos como atendida
                        if solicitud_id:
                            solicitud = SolicitudBackup.objects.get(id=solicitud_id)
                            solicitud.estado = SolicitudBackup.EstadoSolicitud.ATENDIDA
                            solicitud.atendido_por = request.user
                            solicitud.fecha_atencion = timezone.now()
                            solicitud.vehiculo_asignado = vehiculo
                            solicitud.save()
                    else:
                        messages.error(request, f"No se puede asignar un respaldo. El vehículo principal de {chofer_solicitante.get_full_name()} no está en el taller.")

                return redirect('gestion_backups')
            except Vehiculo.DoesNotExist:
                messages.error(request, "El vehículo de respaldo no fue encontrado.")
                return redirect('gestion_backups')


    backups_disponibles = Vehiculo.objects.filter(es_backup=True, estado_actual=Vehiculo.EstadoVehiculo.DISPONIBLE)
    backups_asignados = Vehiculo.objects.filter(es_backup=True, estado_actual__in=[Vehiculo.EstadoVehiculo.ASIGNADO, Vehiculo.EstadoVehiculo.EN_RUTA])
    solicitudes_pendientes = SolicitudBackup.objects.filter(estado=SolicitudBackup.EstadoSolicitud.PENDIENTE).select_related('chofer')
    form = AsignarBackupForm()
    context = {
        'form': form, 
        'backups_disponibles': backups_disponibles, 
        'backups_asignados': backups_asignados,
        'solicitudes_pendientes': solicitudes_pendientes,
    }
    return render(request, 'coordinacion/gestion_backups.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def reporte_intercambios(request):
    """
    Muestra un historial de los movimientos de vehículos de respaldo.
    """
    historial = Historial_Cambios.objects.filter(
        descripcion__icontains='backup'
    ).select_related('usuario').order_by('-fecha_cambio')

    context = {'historial': historial}
    return render(request, 'coordinacion/reporte_intercambios.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION])
def reporte_entradas_salidas(request):
    """
    Muestra un historial de las entradas y salidas de vehículos para mantenimiento
    registradas por los guardias.
    """
    historial = Historial_Cambios.objects.filter(
        Q(descripcion__icontains='ingresó al taller para mantenimiento') |
        Q(descripcion__icontains='salió del recinto tras finalizar mantenimiento')
    ).select_related('usuario').order_by('-fecha_cambio')

    context = {'historial': historial}
    return render(request, 'coordinacion/reporte_entradas_salidas.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION, Usuario.Roles.JEFE_TALLER])
def gestion_insumos(request):
    """
    Pantalla para que Coordinación apruebe o rechacen insumos.
    """
    insumos_pendientes = Insumo.objects.filter(
        estado_aprobacion=Insumo.EstadoAprobacion.PENDIENTE
    ).select_related(
        'mantenimiento__vehiculo', 'solicitado_por'
    ).order_by('fecha_solicitud')

    insumos_procesados = Insumo.objects.filter(
        ~Q(estado_aprobacion=Insumo.EstadoAprobacion.PENDIENTE)
    ).select_related(
        'mantenimiento__vehiculo', 'solicitado_por', 'aprobado_por'
    ).order_by('-fecha_aprobacion')[:20] # Mostramos solo los últimos 20 procesados para no saturar la vista.

    context = {
        'insumos_pendientes': insumos_pendientes,
        'insumos_procesados': insumos_procesados,
    }
    return render(request, 'coordinacion/gestion_insumos.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.COORDINACION, Usuario.Roles.JEFE_TALLER])
def procesar_insumo(request, insumo_id):
    """
    Vista que maneja la lógica de aprobar o rechazar un insumo específico.
    """
    insumo = get_object_or_404(Insumo, id=insumo_id)
    if request.method == 'POST' and insumo.estado_aprobacion == Insumo.EstadoAprobacion.PENDIENTE:
        accion = request.POST.get('accion')

        if accion in ['aprobar', 'rechazar']:
            insumo.aprobado_por = request.user
            insumo.fecha_aprobacion = timezone.now()
            
            if accion == 'aprobar':
                insumo.estado_aprobacion = Insumo.EstadoAprobacion.APROBADO
                messages.success(request, f"Insumo '{insumo.nombre_insumo}' APROBADO.")
                desc_historial = f"Aprobó insumo '{insumo.nombre_insumo}' para mant. #{insumo.mantenimiento.id}."
            else: # rechazar
                insumo.estado_aprobacion = Insumo.EstadoAprobacion.RECHAZADO
                messages.warning(request, f"Insumo '{insumo.nombre_insumo}' RECHAZADO.")
                desc_historial = f"Rechazó insumo '{insumo.nombre_insumo}' para mant. #{insumo.mantenimiento.id}."
            
            insumo.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Insumo",
                id_registro_afectado=insumo.id,
                descripcion=desc_historial
            )
        else:
            messages.error(request, "Acción no válida.")

    return redirect('gestion_insumos')

@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def intercambio_vehiculo(request):
    """
    Permite al Guardia procesar el intercambio: el chofer devuelve un backup
    y retira su vehículo principal ya reparado.
    """
    if request.method == 'POST':
        chofer_id = request.POST.get('chofer_id')
        try:
            chofer = Usuario.objects.get(id=chofer_id)
            
            # 1. Encontrar y procesar el vehículo de respaldo
            backup = Vehiculo.objects.filter(chofer_asignado=chofer, es_backup=True, estado_actual=Vehiculo.EstadoVehiculo.EN_RUTA).first()
            if backup:
                backup.chofer_asignado = None
                backup.estado_actual = Vehiculo.EstadoVehiculo.DISPONIBLE
                backup.save()
            
            # 2. Encontrar el mantenimiento validado del vehículo principal
            mantenimiento_validado = Mantenimiento.objects.get(
                vehiculo__chofer_asignado=chofer,
                vehiculo__es_backup=False,
                estado=Mantenimiento.Estado.VALIDADO
            )
            vehiculo_principal = mantenimiento_validado.vehiculo
            vehiculo_principal.estado_actual = Vehiculo.EstadoVehiculo.DISPONIBLE
            vehiculo_principal.save() # El estado cambiará a EN_RUTA en el registro de salida.

            # 3. Finalizar el ciclo de mantenimiento
            mantenimiento_validado.estado = Mantenimiento.Estado.FINALIZADO
            mantenimiento_validado.fecha_salida_real = timezone.now()
            mantenimiento_validado.save()

            # 4. Registrar en el historial
            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Vehiculo",
                id_registro_afectado=chofer.id,
                descripcion=f"Intercambio procesado para {chofer.get_full_name()}. Devuelve backup {backup.patente if backup else 'N/A'} y retira {vehiculo_principal.patente}."
            )
            messages.success(request, f"Intercambio para {chofer.get_full_name()} procesado con éxito.")

        except Usuario.DoesNotExist:
            messages.error(request, "El chofer especificado no existe.")
        except Mantenimiento.DoesNotExist:
            messages.error(request, "No se encontró un mantenimiento validado para este chofer.")
        
        return redirect('intercambio_vehiculo')

    # Para el GET, mostramos solo los choferes que están usando un backup y cuyo vehículo principal está listo.
    choferes_con_intercambio_pendiente = Usuario.objects.filter(
        vehiculos__es_backup=True,
        vehiculos__estado_actual=Vehiculo.EstadoVehiculo.EN_RUTA
    ).filter(
        mantenimientos__estado=Mantenimiento.Estado.VALIDADO
    ).distinct()

    context = {'choferes_pendientes': choferes_con_intercambio_pendiente}
    return render(request, 'guardia/intercambio_vehiculo.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.MECANICO])
def mecanico_dashboard(request):
    """
    Panel principal para el Mecánico.
    Separa los trabajos en dos listas: los que están activos y los que ya ha completado.
    """
    mantenimientos_activos = Mantenimiento.objects.filter(
        mecanico_asignado=request.user,
        estado__in=[
            Mantenimiento.Estado.DIAGNOSTICO,
            Mantenimiento.Estado.EN_REPARACION
        ]
    ).order_by('agenda__hora_inicio')

    # Notificación de trabajos rechazados
    for mant in mantenimientos_activos:
        if mant.estado == Mantenimiento.Estado.DIAGNOSTICO:
            # Un mantenimiento vuelve a 'Diagnóstico' si es rechazado.
            # Buscamos la última observación de rechazo para este mantenimiento.
            observacion_rechazo = Observacion.objects.filter(
                mantenimiento=mant,
                texto__startswith='RECHAZO DE SUPERVISOR:'
            ).order_by('-fecha').first()

            if observacion_rechazo:
                motivo = observacion_rechazo.texto.replace("RECHAZO DE SUPERVISOR: ", "")
                mensaje = f"**Trabajo Rechazado (Patente {mant.vehiculo.patente}):** El supervisor devolvió el trabajo con la siguiente observación: \"{motivo}\""
                messages.error(request, mensaje)

    # --- Consulta 2: Trabajos Completados ---
    mantenimientos_completados = Mantenimiento.objects.filter(
        mecanico_asignado=request.user,
        estado__in=[
            Mantenimiento.Estado.REPARADO,
            Mantenimiento.Estado.VALIDADO,
            Mantenimiento.Estado.FINALIZADO
        ]
    ).order_by('-fecha_salida_real')

    context = {
        'mantenimientos_activos': mantenimientos_activos,
        'mantenimientos_completados': mantenimientos_completados
    }
    return render(request, 'mecanico/mecanico.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def guardia_dashboard(request):
    """
    Panel principal para el Guardia. Redirige a la función más común (registro de entrada).
    """
    return redirect('registro_entrada')


@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def supervisor_dashboard(request):
    """
    Panel principal para el Supervisor.
    Muestra una lista prioritaria de mantenimientos que los mecánicos han marcado
    como 'REPARADO' y que están pendientes de su validación.
    """
    mantenimientos_por_validar = Mantenimiento.objects.filter(
        estado=Mantenimiento.Estado.REPARADO
    ).select_related('vehiculo', 'mecanico_asignado').order_by('fecha_solicitud')

    context = {
        'mantenimientos_por_validar': mantenimientos_por_validar,
    }
    return render(request, 'supervisor/supervisor.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def supervisor_reportes(request):
    """
    Genera KPIs y permite exportar datos detallados de mantenimientos a un archivo Excel.
    Permite filtrar por mes o por año completo.
    """
    today = timezone.now()
    year = int(request.GET.get('year', today.year))
    month_str = request.GET.get('month', str(today.month)) 

    # Si el mes es 'all', la variable `month` será None para no filtrar por mes.
    if month_str == 'all':
        month = None
    else:
        month = int(month_str)

    # Lógica de Exportación
    if 'export' in request.GET:
        mantenimientos_query = Mantenimiento.objects.filter(
            fecha_salida_real__year=year,
            estado=Mantenimiento.Estado.FINALIZADO
        ).select_related(
            'vehiculo', 'mecanico_asignado', 'taller', 'vehiculo__sitio', 'solicitado_por'
        )
        
        if month:
            mantenimientos_query = mantenimientos_query.filter(fecha_salida_real__month=month)

        # Para evitar múltiples consultas a la base de datos dentro del bucle (problema N+1),
        # traemos todas las solicitudes de backup relevantes de una sola vez.
        chofer_ids = [m.solicitado_por_id for m in mantenimientos_query if m.solicitado_por_id]
        
        solicitudes_backup = SolicitudBackup.objects.filter(
            chofer_id__in=chofer_ids,
            estado=SolicitudBackup.EstadoSolicitud.ATENDIDA
        ).select_related('vehiculo_asignado')

        # Organizamos los backups en un diccionario para un acceso rápido.
        backups_por_chofer = {}
        for sb in solicitudes_backup:
            backups_por_chofer.setdefault(sb.chofer_id, []).append(sb)

        # Preparamos los datos para pandas
        data_list = []
        for mant in mantenimientos_query:
            horas_en_taller = 'N/A'
            if mant.fecha_hora_llegada and mant.fecha_salida_real:
                delta = mant.fecha_salida_real - mant.fecha_hora_llegada
                horas_en_taller = round(delta.total_seconds() / 3600, 2)

            backup_otorgado = "No"
            backup_patente = "N/A"
            if mant.solicitado_por_id in backups_por_chofer:
                for solicitud_backup in backups_por_chofer[mant.solicitado_por_id]:
                    # Verificamos si la fecha de atención del backup está dentro del rango del mantenimiento
                    if mant.fecha_hora_llegada <= solicitud_backup.fecha_atencion <= mant.fecha_salida_real:
                        if solicitud_backup.vehiculo_asignado:
                            backup_otorgado = "Sí"
                            backup_patente = solicitud_backup.vehiculo_asignado.patente
                            break # Si encontramos un backup en el rango, paramos de buscar.

            data_list.append({
                'ID Mantenimiento': mant.id,
                'Patente': mant.vehiculo.patente,
                'Vehículo': f"{mant.vehiculo.marca} {mant.vehiculo.modelo}",
                'Mecánico': mant.mecanico_asignado.display_name if mant.mecanico_asignado else "N/A",
                'Especialidad Mecánico': mant.mecanico_asignado.get_especialidad_display() if mant.mecanico_asignado else "N/A",
                'Chofer': mant.solicitado_por.display_name if mant.solicitado_por else "N/A",
                'Fecha Solicitud': mant.fecha_solicitud.strftime('%Y-%m-%d'),
                'Fecha Finalización': mant.fecha_salida_real.strftime('%Y-%m-%d'),
                'Horas en Taller': horas_en_taller,
                'Taller': mant.taller.nombre_taller if mant.taller else "N/A",
                'Sitio del Vehículo': mant.vehiculo.sitio.nombre_sitio if mant.vehiculo.sitio else "N/A",
                'Diagnóstico': mant.diagnostico,
                'Trabajo Realizado': mant.trabajo_realizado,
                'Backup Otorgado': backup_otorgado,
                'Patente Backup': backup_patente,
            })

        # Usamos pandas para crear un archivo Excel en memoria.
        df = pd.DataFrame(data_list)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Mantenimientos')
        output.seek(0)

        # Servimos el archivo Excel generado.
        response = HttpResponse(output, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="reporte_mantenimientos_{year}-{month_str}.xlsx"'
        return response

    #Lógica para mostrar KPIs en la página
    mantenimientos_periodo = Mantenimiento.objects.filter(
        fecha_salida_real__year=year,
        estado=Mantenimiento.Estado.FINALIZADO
    )
    if month:
        mantenimientos_periodo = mantenimientos_periodo.filter(fecha_salida_real__month=month)
    
    total_mantenimientos_mes = mantenimientos_periodo.count()

    insumos_mes = Insumo.objects.filter(mantenimiento__in=mantenimientos_periodo)
    total_insumos_mes = insumos_mes.count()

    tiempo_promedio_reparacion = mantenimientos_periodo.aggregate(
        avg_time=Avg(F('fecha_salida_real') - F('fecha_hora_llegada'))
    )['avg_time']

    top_insumos = insumos_mes.values('nombre_insumo').annotate(
        total=Count('nombre_insumo')
    ).order_by('-total')[:5]

    years_disponibles = range(2024, today.year + 2) # Rango de años para el filtro.
    meses_disponibles = [
        (1, 'Enero'), (2, 'Febrero'), (3, 'Marzo'), (4, 'Abril'),
        (5, 'Mayo'), (6, 'Junio'), (7, 'Julio'), (8, 'Agosto'),
        (9, 'Septiembre'), (10, 'Octubre'), (11, 'Noviembre'), (12, 'Diciembre')
    ]

    context = {
        'total_mantenimientos_mes': total_mantenimientos_mes,
        'total_insumos_mes': total_insumos_mes,
        'tiempo_promedio_reparacion': tiempo_promedio_reparacion,
        'top_insumos': top_insumos,
        'selected_year': year,
        'selected_month': month_str,
        'years_disponibles': years_disponibles,
        'meses_disponibles': meses_disponibles,
    }
    return render(request, 'supervisor/reportes.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.JEFE_TALLER])
def jefe_taller_dashboard(request):
    #Obtenemos los trabajos que el Guardia marcó como 'EN_TALLER'
    trabajos_pendientes = Mantenimiento.objects.filter(
        estado=Mantenimiento.Estado.EN_TALLER,
        mecanico_asignado__isnull=True
    ).order_by('fecha_hora_llegada')

    trabajos_para_asignar = []
    for trabajo in trabajos_pendientes:
        # Para cada trabajo, buscamos mecánicos y los ordenamos por prioridad.
        tipo_requerido = trabajo.agenda.tipo_atencion
        
        mecanicos_disponibles = Usuario.objects.filter(rol=Usuario.Roles.MECANICO).annotate(
            orden_prioridad=Case(
                When(especialidad=tipo_requerido, then=Value(1)),
                When(especialidad=Usuario.Especialidades.GENERAL, then=Value(2)),
                default=Value(3),
            )
        ).order_by('orden_prioridad', 'first_name')

        trabajos_para_asignar.append({
            'trabajo': trabajo,
            'mecanicos_disponibles': mecanicos_disponibles
        })

    context = {
        'trabajos_para_asignar': trabajos_para_asignar
    }
    return render(request, 'jefe_taller/jefe_taller.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.JEFE_TALLER])
def asignar_mantenimiento(request, mantenimiento_id):
    """
    Esta vista se activa cuando el Jefe de Taller presiona "Asignar".
    El ID del mecánico ahora viene en el POST.
    """
    if request.method == 'POST':
        mecanico_id = request.POST.get('mecanico')
        if not mecanico_id:
            messages.error(request, "Debe seleccionar un mecánico para asignar el trabajo.")
            return redirect('jefe_taller_dashboard')
        try:
            trabajo = Mantenimiento.objects.get(id=mantenimiento_id)
            mecanico = Usuario.objects.get(id=mecanico_id)
            
            trabajo.mecanico_asignado = mecanico
            trabajo.estado = Mantenimiento.Estado.DIAGNOSTICO
            trabajo.save()
            
            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Mantenimiento",
                id_registro_afectado=trabajo.id,
                descripcion=f"Jefe de Taller asignó mant. de {trabajo.vehiculo.patente} a {mecanico.display_name}."
            )
            
            messages.success(request, f"Trabajo de {trabajo.vehiculo.patente} asignado a {mecanico.display_name}.")
            
        except Mantenimiento.DoesNotExist:
            messages.error(request, "El trabajo que intentas asignar no existe.")
        except Usuario.DoesNotExist:
            messages.error(request, "El mecánico seleccionado no existe.")
            
    return redirect('jefe_taller_dashboard')

@login_required
@role_required(allowed_roles=[Usuario.Roles.MECANICO])
def detalle_mantenimiento(request, mantenimiento_id):
    """
    Pantalla: Registro de Mantenimiento / Diagnóstico
    (Actualizada para manejar Pausas)
    """
    mantenimiento = get_object_or_404(Mantenimiento, id=mantenimiento_id)
    
    if mantenimiento.mecanico_asignado != request.user:
        messages.error(request, "No tienes permiso para ver este mantenimiento.")
        return redirect('mecanico_dashboard')
        
    es_editable = mantenimiento.estado not in [ # Un mantenimiento cerrado ya no se puede editar.
        Mantenimiento.Estado.REPARADO,
        Mantenimiento.Estado.VALIDADO,
        Mantenimiento.Estado.FINALIZADO
    ]

    if request.method == 'POST':
        
        form_name = request.POST.get('form_name') # Identificamos qué formulario se envió.

        if not es_editable:
            messages.error(request, "Este mantenimiento ya está cerrado y no se puede modificar.")
            return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)
        
        if form_name == 'diagnostico':
            diag_form = DiagnosticoForm(request.POST, instance=mantenimiento)
            if diag_form.is_valid():
                # Al guardar el primer diagnóstico, el estado pasa a 'EN_REPARACION'.
                if mantenimiento.estado == Mantenimiento.Estado.DIAGNOSTICO:
                    mantenimiento.estado = Mantenimiento.Estado.EN_REPARACION
                
                diag_form.save()
                
                Historial_Cambios.objects.create(
                    usuario=request.user,
                    tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                    tabla_afectada="Mantenimiento",
                    id_registro_afectado=mantenimiento.id,
                    descripcion="Mecánico actualizó diagnóstico/trabajo."
                )
                messages.success(request, "Diagnóstico actualizado.")
        
        elif form_name == 'insumo':
            insumo_form = InsumoForm(request.POST)
            if insumo_form.is_valid():
                insumo = insumo_form.save(commit=False)
                insumo.mantenimiento = mantenimiento
                insumo.solicitado_por = request.user
                insumo.save()
                
                Historial_Cambios.objects.create(
                    usuario=request.user,
                    tipo_cambio=Historial_Cambios.TipoCambio.CREACION,
                    tabla_afectada="Insumo",
                    id_registro_afectado=insumo.id,
                    descripcion=f"Mecánico añadió insumo: {insumo.nombre_insumo} (Cant: {insumo.cantidad})."
                )
                messages.success(request, f"Insumo '{insumo.nombre_insumo}' añadido.")
        
        elif form_name == 'foto':
            foto_form = FotoMantenimientoForm(request.POST, request.FILES)
            if foto_form.is_valid():
                foto = foto_form.save(commit=False)
                foto.mantenimiento = mantenimiento
                foto.subido_por = request.user
                foto.save()
                
                Historial_Cambios.objects.create(
                    usuario=request.user,
                    tipo_cambio=Historial_Cambios.TipoCambio.CREACION,
                    tabla_afectada="FotoMantenimiento",
                    id_registro_afectado=foto.id,
                    descripcion="Mecánico subió foto de evidencia."
                )
                messages.success(request, "Foto subida con éxito.")
        
        return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)

    # Formularios
    diag_form = DiagnosticoForm(instance=mantenimiento)
    insumo_form = InsumoForm()
    foto_form = FotoMantenimientoForm()
    pausa_form = PausaForm()

    insumos_existentes = Insumo.objects.filter(mantenimiento=mantenimiento)
    fotos_existentes = FotoMantenimiento.objects.filter(mantenimiento=mantenimiento)
    pausa_activa = Pausa.objects.filter(
        mantenimiento=mantenimiento,
        fin_pausa__isnull=True
    ).first()

    context = {
        'mantenimiento': mantenimiento,
        'diag_form': diag_form,
        'insumo_form': insumo_form,
        'foto_form': foto_form,
        'pausa_form': pausa_form,
        'insumos_existentes': insumos_existentes,
        'fotos_existentes': fotos_existentes,
        'pausa_activa': pausa_activa,
        'es_editable': es_editable,
    }
    
    return render(request, 'mecanico/detalle_mantenimiento.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.MECANICO])
def iniciar_pausa(request, mantenimiento_id):
    """
    Crea un nuevo registro de Pausa.    
    """
    mantenimiento = get_object_or_404(Mantenimiento, id=mantenimiento_id)
    
    if mantenimiento.mecanico_asignado != request.user:
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect('mecanico_dashboard')

    if request.method == 'POST':
        # Validamos si ya existe una pausa activa
        pausa_existente = Pausa.objects.filter(mantenimiento=mantenimiento, fin_pausa__isnull=True).exists()
        
        if not pausa_existente:
            form = PausaForm(request.POST)
            if form.is_valid():
                pausa = form.save(commit=False)
                pausa.mantenimiento = mantenimiento
                pausa.mecanico = request.user
                # inicio_pausa se setea automáticamente (auto_now_add=True)
                pausa.save()
                
                Historial_Cambios.objects.create(
                    usuario=request.user,
                    tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                    tabla_afectada="Pausa",
                    id_registro_afectado=pausa.id,
                    descripcion=f"Mecánico inició pausa. Motivo: {pausa.motivo}"
                )
                messages.success(request, f"Pausa iniciada. Motivo: {pausa.motivo}")
            else:
                messages.error(request, "Debe especificar un motivo para la pausa.")
        else:
            messages.warning(request, "Ya hay una pausa activa para este mantenimiento.")

    return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)


@login_required
@role_required(allowed_roles=[Usuario.Roles.MECANICO])
def terminar_pausa(request, mantenimiento_id):
    """
    Cierra la pausa activa actualizando el campo 'fin_pausa'.
    """
    mantenimiento = get_object_or_404(Mantenimiento, id=mantenimiento_id)
    
    # Seguridad
    if mantenimiento.mecanico_asignado != request.user:
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect('mecanico_dashboard')

    if request.method == 'POST':
        pausa_activa = Pausa.objects.filter(
            mantenimiento=mantenimiento,
            fin_pausa__isnull=True
        ).first()
        
        if pausa_activa:
            pausa_activa.fin_pausa = timezone.now() # Usamos timezone
            pausa_activa.save()
            
            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Pausa",
                id_registro_afectado=pausa_activa.id,
                descripcion="Mecánico terminó la pausa."
            )
            messages.success(request, "Pausa terminada. Puedes continuar con el trabajo.")
        else:
            messages.warning(request, "No hay ninguna pausa activa para terminar.")
            
    return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)

@login_required
@role_required(allowed_roles=[Usuario.Roles.MECANICO])
def cerrar_reparacion(request, mantenimiento_id):
    """
    Cambia el estado a 'REPARADO' y lo envía al Supervisor.
    """
    mantenimiento = get_object_or_404(Mantenimiento, id=mantenimiento_id)
    
    if mantenimiento.mecanico_asignado != request.user:
        messages.error(request, "No tienes permiso para esta acción.")
        return redirect('mecanico_dashboard')

    if request.method == 'POST':
        if not mantenimiento.diagnostico or not mantenimiento.trabajo_realizado:
            messages.error(request, "Debe completar el Diagnóstico y el Trabajo Realizado antes de cerrar.")
            return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)
            
        mantenimiento.estado = Mantenimiento.Estado.REPARADO
        # La fecha de finalización se registrará cuando el supervisor valide o el guardia despache.
        # Aquí solo se marca el fin del trabajo del mecánico.
        mantenimiento.save()
        
        # 3. Creamos el registro de auditoría
        Historial_Cambios.objects.create(
            usuario=request.user,
            tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
            tabla_afectada="Mantenimiento",
            id_registro_afectado=mantenimiento.id,
            descripcion="Mecánico marcó la reparación como finalizada."
        )
        
        messages.success(request, "Trabajo finalizado y enviado a validación del Supervisor.")
        
        return redirect('mecanico_dashboard')

    return redirect('detalle_mantenimiento', mantenimiento_id=mantenimiento.id)


@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def validar_reparacion(request, mantenimiento_id):
    """
    Muestra toda la información de un mantenimiento para que el supervisor la revise.
    """
    mantenimiento = get_object_or_404(
        Mantenimiento, 
        id=mantenimiento_id, 
        estado=Mantenimiento.Estado.REPARADO
    )

    if request.method == 'POST':
        accion = request.POST.get('accion')
        observacion_texto = request.POST.get('observaciones_supervisor', '').strip()

        if accion == 'validar':
            mantenimiento.estado = Mantenimiento.Estado.VALIDADO
            mantenimiento.validado_por = request.user
            mantenimiento.fecha_validacion = timezone.now()
            mantenimiento.save()

            # El vehículo ahora está listo para ser retirado por el chofer.
            vehiculo = mantenimiento.vehiculo
            vehiculo.estado_actual = Vehiculo.EstadoVehiculo.DISPONIBLE
            vehiculo.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Mantenimiento",
                id_registro_afectado=mantenimiento.id,
                descripcion=f"Reparación validada por supervisor. Patente: {mantenimiento.vehiculo.patente}"
            )

            messages.success(request, f"La reparación del vehículo {mantenimiento.vehiculo.patente} ha sido validada correctamente.")
            return redirect('supervisor_dashboard')

        elif accion == 'rechazar':
            if not observacion_texto:
                messages.error(request, "Para rechazar una reparación, debe dejar una observación explicando el motivo.")
            else:
                # 1. Cambiamos el estado del mantenimiento de vuelta a Diagnóstico
                mantenimiento.estado = Mantenimiento.Estado.DIAGNOSTICO
                mantenimiento.save()

                # Añadimos la observación de rechazo
                Observacion.objects.create(
                    mantenimiento=mantenimiento,
                    usuario=request.user,
                    texto=f"RECHAZO DE SUPERVISOR: {observacion_texto}"
                )

                # Creamos un registro en el historial sobre el rechazo
                Historial_Cambios.objects.create(
                    usuario=request.user,
                    tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                    tabla_afectada="Mantenimiento",
                    id_registro_afectado=mantenimiento.id,
                    descripcion=f"Reparación de {mantenimiento.vehiculo.patente} rechazada. Vuelve a diagnóstico."
                )

                messages.warning(request, f"La reparación ha sido rechazada y se ha notificado con su observación.")
                return redirect('supervisor_dashboard')

    # Para el método GET, cargamos toda la información relevante del mantenimiento.
    fotos = mantenimiento.fotos.all()
    insumos = mantenimiento.insumos.all()
    observaciones = mantenimiento.observaciones.all().order_by('-fecha')

    context = {
        'mantenimiento': mantenimiento,
        'fotos': fotos,
        'insumos': insumos,
        'observaciones': observaciones,
    }
    return render(request, 'supervisor/validar_reparacion.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def seguimiento_mantenimientos(request):
    """
    Muestra una lista de todos los mantenimientos en el sistema,
    permitiendo al supervisor tener una visión completa.
    """
    filtro_patente = request.GET.get('patente', '').strip()
    filtro_estado = request.GET.get('estado', '')

    todos_los_mantenimientos = Mantenimiento.objects.select_related(
        'vehiculo', 'mecanico_asignado', 'solicitado_por'
    ).order_by('-fecha_solicitud')

    if filtro_patente:
        todos_los_mantenimientos = todos_los_mantenimientos.filter(vehiculo__patente__icontains=filtro_patente)
    
    if filtro_estado:
        todos_los_mantenimientos = todos_los_mantenimientos.filter(estado=filtro_estado)

    # Pasamos los filtros actuales de vuelta a la plantilla para que se mantengan en los inputs.
    context = {
        'mantenimientos': todos_los_mantenimientos,
        'estados_posibles': Mantenimiento.Estado.choices, # Pasamos los estados para el dropdown
        'filtro_patente_actual': filtro_patente,
        'filtro_estado_actual': filtro_estado,
    }

    return render(request, 'supervisor/seguimiento_mantenimientos.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def seleccionar_vehiculo_documentos(request):
    """
    Paso 1: Muestra una lista de todos los vehículos para que el supervisor elija uno.
    Permite filtrar por patente.
    """
    filtro_patente = request.GET.get('patente', '').strip()

    vehiculos = Vehiculo.objects.all().order_by('patente')

    if filtro_patente:
        vehiculos = vehiculos.filter(patente__icontains=filtro_patente)

    context = {
        'vehiculos': vehiculos,
        'filtro_patente_actual': filtro_patente,
    }
    return render(request, 'supervisor/seleccionar_vehiculo.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def gestion_documentos_por_vehiculo(request, patente):
    """
    Paso 2: Gestiona (ve, sube) los documentos para un vehículo específico.
    """
    vehiculo = get_object_or_404(Vehiculo, patente=patente)

    if request.method == 'POST':
        form = DocumentoForm(request.POST, request.FILES, initial={'vehiculo': vehiculo})
        if form.is_valid():
            documento = form.save(commit=False)
            documento.subido_por = request.user
            documento.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.CREACION,
                tabla_afectada="Documento",
                id_registro_afectado=documento.id,
                descripcion=f"Subió '{documento.nombre_documento}' para vehículo {vehiculo.patente}."
            )
            messages.success(request, "Documento subido correctamente.")
            return redirect('gestion_documentos_por_vehiculo', patente=vehiculo.patente)
    else:
        form = DocumentoForm(initial={'vehiculo': vehiculo})
        form.fields['vehiculo'].widget = forms.HiddenInput() # Ocultamos el selector de vehículo.

    documentos_del_vehiculo = Documento.objects.filter(vehiculo=vehiculo).select_related('subido_por').order_by('-fecha_carga')

    context = {
        'vehiculo': vehiculo,
        'form': form,
        'documentos': documentos_del_vehiculo,
    }
    return render(request, 'supervisor/gestion_documentos.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.SUPERVISOR])
def eliminar_documento(request, documento_id):
    """
    Procesa la eliminación de un documento. Solo accesible por POST para seguridad.
    """
    documento = get_object_or_404(Documento, id=documento_id)
    if request.method == 'POST':
        patente_vehiculo = documento.vehiculo.patente
        documento.delete()
        messages.warning(request, f"El documento '{documento.nombre_documento}' ha sido eliminado correctamente.")
        return redirect('gestion_documentos_por_vehiculo', patente=patente_vehiculo)
    return redirect('seleccionar_vehiculo_documentos')
  

#FUNCIONALIDADES DEL GUARDIA
@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def registro_entrada(request):
    """
    Permite al guardia registrar la entrada de un vehículo al recinto.
    Si el vehículo tiene una cita agendada, actualiza el estado del mantenimiento a 'EN_TALLER'.
    En todos los casos, el vehículo queda 'EN_TALLER' y se desasigna del chofer.
    """
    from .models import Observacion # Importación local
    mantenimientos_agendados = Mantenimiento.objects.filter(
        estado=Mantenimiento.Estado.AGENDADO
    ).select_related('vehiculo').order_by('vehiculo__patente')
    vehiculos_para_entrar = [m.vehiculo for m in mantenimientos_agendados]

    if request.method == 'POST':
        patente = request.POST.get('patente')
        observaciones_guardia = request.POST.get('observaciones', '').strip()
        fotos = request.FILES.getlist('fotos')

        # Buscamos si hay un mantenimiento agendado para este vehículo
        mantenimiento_agendado = Mantenimiento.objects.filter(
            vehiculo__patente=patente,
            estado=Mantenimiento.Estado.AGENDADO
        ).select_related('vehiculo').order_by('fecha_solicitud').first()

        if mantenimiento_agendado:
            vehiculo = mantenimiento_agendado.vehiculo
            now = timezone.now()

            # Si hay cita, actualizamos el mantenimiento y el vehículo para el taller
            mantenimiento_agendado.fecha_hora_llegada = now
            mantenimiento_agendado.estado = Mantenimiento.Estado.EN_TALLER
            mantenimiento_agendado.save()
            
            # Guardar observaciones y fotos asociadas al mantenimiento
            if observaciones_guardia:
                Observacion.objects.create(
                    mantenimiento=mantenimiento_agendado,
                    usuario=request.user,
                    texto=f"OBSERVACIÓN DE GUARDIA (ENTRADA): {observaciones_guardia}"
                )
            
            for foto_file in fotos:
                FotoMantenimiento.objects.create(
                    mantenimiento=mantenimiento_agendado,
                    imagen=foto_file,
                    descripcion="Foto de ingreso registrada por guardia.",
                    subido_por=request.user
                )

            # El vehículo pasa a estar EN_TALLER
            vehiculo.estado_actual = Vehiculo.EstadoVehiculo.EN_TALLER
            vehiculo.save()

            descripcion_historial = f"Vehículo {vehiculo.patente} ingresó al taller para mantenimiento #{mantenimiento_agendado.id} a las {now.strftime('%H:%M')}."
            
            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Vehiculo",
                id_registro_afectado=vehiculo.patente,
                descripcion=descripcion_historial
            )

            msg = f"Vehículo {vehiculo.patente} ingresado al taller para su cita."
            if fotos:
                msg += f" Se guardaron {len(fotos)} foto(s)."
            if observaciones_guardia:
                msg += " Se guardó una observación."
            messages.success(request, msg)

        else: # Si no hay cita, no se permite el ingreso.
            messages.error(request, f"El vehículo con patente '{patente}' no tiene una cita agendada y no puede ingresar.")

    context = {
        'vehiculos_para_entrar': vehiculos_para_entrar
    }
    return render(request, 'guardia/RegistroEntrada.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def registro_salida(request):
    """
    Permite al guardia registrar la salida de un vehículo.
    Si se asigna un chofer, el vehículo pasa a 'EN_RUTA'. De lo contrario, queda 'DISPONIBLE'.
    Si la salida corresponde a un mantenimiento recién validado, lo marca como 'FINALIZADO'.
    """
    mantenimientos_validados = Mantenimiento.objects.filter(
        estado=Mantenimiento.Estado.VALIDADO
    ).select_related('vehiculo').order_by('vehiculo__patente')
    vehiculos_para_salir = [m.vehiculo for m in mantenimientos_validados]

    # Filtramos los choferes para mostrar solo aquellos que tienen un vehículo en el taller.
    # Un vehículo está en el taller si tiene un mantenimiento en cualquiera de estos estados.
    choferes_con_vehiculo_en_taller = Usuario.objects.filter(
        rol=Usuario.Roles.CHOFER,
        is_active=True,
        vehiculos__mantenimientos__estado__in=[
            Mantenimiento.Estado.EN_TALLER,
            Mantenimiento.Estado.DIAGNOSTICO,
            Mantenimiento.Estado.EN_REPARACION,
            Mantenimiento.Estado.REPARADO,
            Mantenimiento.Estado.VALIDADO,
        ]
    ).distinct().order_by('first_name', 'last_name')
    if request.method == 'POST':
        patente = request.POST.get('patente')
        chofer_id = request.POST.get('chofer')
        now = timezone.now()

        try:
            vehiculo = Vehiculo.objects.get(patente=patente)
            chofer_asignado = None

            mantenimiento_finalizado = Mantenimiento.objects.filter(
                vehiculo=vehiculo,
                estado=Mantenimiento.Estado.VALIDADO
            ).order_by('-fecha_validacion').first()

            if mantenimiento_finalizado:
                mantenimiento_finalizado.fecha_salida_real = now
                mantenimiento_finalizado.estado = Mantenimiento.Estado.FINALIZADO
                mantenimiento_finalizado.save()
                descripcion_historial = f"Vehículo {vehiculo.patente} salió del recinto tras finalizar mantenimiento #{mantenimiento_finalizado.id}."
                messages.success(request, f"Vehículo {vehiculo.patente} salió correctamente tras finalizar su mantenimiento.")
            else:
                descripcion_historial = f"Vehículo {vehiculo.patente} salió del recinto."
                messages.success(request, f"Vehículo {vehiculo.patente} salió correctamente.")

            # Si se seleccionó un chofer, se le asigna el vehículo y se pone en ruta.
            if chofer_id:
                try:
                    chofer_asignado = Usuario.objects.get(id=chofer_id)
                    vehiculo.chofer_asignado = chofer_asignado
                    vehiculo.estado_actual = Vehiculo.EstadoVehiculo.EN_RUTA
                    descripcion_historial += f" Asignado a {chofer_asignado.display_name} a las {now.strftime('%H:%M')}."
                except Usuario.DoesNotExist:
                    messages.error(request, "El chofer seleccionado no es válido.")
                    return redirect('registro_salida')
            else:
                vehiculo.estado_actual = Vehiculo.EstadoVehiculo.DISPONIBLE

            vehiculo.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Vehiculo",
                id_registro_afectado=vehiculo.patente,
                descripcion=descripcion_historial
            )
            return redirect('registro_salida')

        except Vehiculo.DoesNotExist:
            messages.error(request, f"No se encontró el vehículo con patente {patente}.")

    context = {'vehiculos': vehiculos_para_salir, 'choferes': choferes_con_vehiculo_en_taller}
    return render(request, 'guardia/RegistroSalida.html', context)


@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def registro_backup(request):
    """
    Flujo simple para que el guardia entregue un vehículo de respaldo a un chofer.
    """
    backups = Vehiculo.objects.filter(
        es_backup=True,
        estado_actual=Vehiculo.EstadoVehiculo.DISPONIBLE
    )

    choferes = Usuario.objects.filter(
        rol=Usuario.Roles.CHOFER,
        is_active=True
    ).order_by('first_name', 'last_name')

    if request.method == 'POST':
        patente = request.POST.get('patente')
        chofer_id = request.POST.get('chofer')

        try:
            vehiculo = Vehiculo.objects.get(patente=patente)
            chofer = Usuario.objects.get(id=chofer_id, rol=Usuario.Roles.CHOFER)

            vehiculo.chofer_asignado = chofer
            vehiculo.estado_actual = Vehiculo.EstadoVehiculo.EN_RUTA
            vehiculo.save()

            Historial_Cambios.objects.create(
                usuario=request.user,
                tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                tabla_afectada="Vehiculo",
                id_registro_afectado=vehiculo.patente,
                descripcion=f"Backup {vehiculo.patente} entregado a {chofer.first_name} {chofer.last_name} a las {timezone.now().strftime('%H:%M')}."
            )

            messages.success(
                request,
                f"Backup {vehiculo.patente} entregado correctamente a {chofer.first_name} {chofer.last_name}."
            )
            return redirect('registro_backup')

        except Vehiculo.DoesNotExist:
            messages.error(request, f"No se encontró el vehículo con patente {patente}.")
        except Usuario.DoesNotExist:
            messages.error(request, f"No se encontró el chofer seleccionado.")

    context = {'backups': backups, 'choferes': choferes}
    return render(request, 'guardia/RegistroBackup.html', context)

@login_required
@role_required(allowed_roles=[Usuario.Roles.GUARDIA])
def guardia_gestion_backups(request):
    """
    Vista para que el Guardia gestione el ciclo de vida de los vehículos de respaldo.
    Permite registrar la salida (cuando el chofer lo retira) y el ingreso (cuando lo devuelve).
    """
    if request.method == 'POST':
        accion = request.POST.get('accion')
        patente = request.POST.get('patente')

        try:
            vehiculo = Vehiculo.objects.get(patente=patente, es_backup=True)
            
            # El coordinador lo asignó, ahora el guardia confirma que el chofer lo retiró.
            if accion == 'registrar_salida' and vehiculo.estado_actual == Vehiculo.EstadoVehiculo.ASIGNADO:
                vehiculo.estado_actual = Vehiculo.EstadoVehiculo.EN_RUTA
                vehiculo.save()
                Historial_Cambios.objects.create(
                    usuario=request.user, tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                    tabla_afectada="Vehiculo", id_registro_afectado=vehiculo.patente,
                    descripcion=f"Guardia registró salida de backup {vehiculo.patente} con chofer {vehiculo.chofer_asignado.display_name}."
                )
                messages.success(request, f"Salida del vehículo de respaldo {vehiculo.patente} registrada.")

            # El chofer devuelve el vehículo de respaldo.
            elif accion == 'registrar_ingreso' and vehiculo.estado_actual == Vehiculo.EstadoVehiculo.EN_RUTA:
                sitio_id = request.POST.get('sitio')
                if not sitio_id:
                    messages.error(request, "Debe seleccionar un sitio de devolución.")
                else:
                    sitio_devolucion = Sitio.objects.get(id=sitio_id)
                    chofer_anterior = vehiculo.chofer_asignado
                    
                    vehiculo.estado_actual = Vehiculo.EstadoVehiculo.DISPONIBLE
                    vehiculo.chofer_asignado = None
                    vehiculo.sitio = sitio_devolucion
                    vehiculo.save()
                    
                    Historial_Cambios.objects.create(
                        usuario=request.user, tipo_cambio=Historial_Cambios.TipoCambio.EDICION,
                        tabla_afectada="Vehiculo", id_registro_afectado=vehiculo.patente,
                        descripcion=f"Guardia registró ingreso de backup {vehiculo.patente} de chofer {chofer_anterior.display_name} en sitio {sitio_devolucion.nombre_sitio}."
                    )
                    messages.success(request, f"Ingreso del vehículo de respaldo {vehiculo.patente} registrado.")
            
            else:
                messages.warning(request, "La acción no se pudo realizar. El estado del vehículo no es el correcto.")

        except Vehiculo.DoesNotExist:
            messages.error(request, "No se encontró el vehículo de respaldo especificado.")
        except Sitio.DoesNotExist:
            messages.error(request, "El sitio seleccionado no es válido.")

        return redirect('guardia_gestion_backups')

    # Para el método GET, separamos los vehículos según su estado para mostrarlos en listas diferentes.
    backups_pendientes_salida = Vehiculo.objects.filter(es_backup=True, estado_actual=Vehiculo.EstadoVehiculo.ASIGNADO)
    backups_en_ruta = Vehiculo.objects.filter(es_backup=True, estado_actual=Vehiculo.EstadoVehiculo.EN_RUTA)
    sitios = Sitio.objects.all()

    context = {
        'pendientes_salida': backups_pendientes_salida,
        'en_ruta': backups_en_ruta,
        'sitios': sitios,
    }
    return render(request, 'guardia/gestion_backups_guardia.html', context)
