from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy, include
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', auth_views.LoginView.as_view(
        template_name='login.html',
        redirect_authenticated_user=True
    ), name='login'),
    
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    # URLs para cambio de contraseña
    path('password_change/', auth_views.PasswordChangeView.as_view(
        template_name='registration/password_change.html',
        success_url=reverse_lazy('password_change_done')
    ), name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='registration/password_change_done.html'
    ), name='password_change_done'),
    #Vistas chofer
    path('dashboard/chofer/', views.chofer_dashboard, name='chofer_dashboard'),
    path('mantenimiento/solicitar/', views.solicitar_atencion, name='solicitar_atencion'),

    # RUTAS PLACEHOLDER PARA OTROS ROLES
    path('dashboard/coordinacion/', views.coordinacion_dashboard, name='coordinacion_dashboard'),
    # URLs de Gestión para Coordinación
    path('gestion/usuarios/', views.user_list, name='user_list'),
    path('gestion/usuarios/crear/', views.user_create, name='user_create'),
    path('gestion/usuarios/editar/<int:pk>/', views.user_edit, name='user_edit'),
    path('gestion/usuarios/desactivar/<int:pk>/', views.user_deactivate, name='user_deactivate'),
    path('gestion/vehiculos/', views.vehicle_list, name='vehicle_list'),
    path('gestion/vehiculos/crear/', views.vehicle_create, name='vehicle_create'),
    path('gestion/vehiculos/editar/<str:pk>/', views.vehicle_edit, name='vehicle_edit'),
    path('gestion/vehiculos/dar_de_baja/<str:pk>/', views.vehicle_deactivate, name='vehicle_deactivate'),
    path('gestion/sitios/', views.sitio_list, name='sitio_list'),
    path('gestion/sitios/crear/', views.sitio_create, name='sitio_create'),
    path('gestion/sitios/editar/<int:pk>/', views.sitio_edit, name='sitio_edit'),
    path('gestion/sitios/eliminar/<int:pk>/', views.sitio_delete, name='sitio_delete'),
    path('gestion/backups/', views.gestion_backups, name='gestion_backups'),
    path('reportes/intercambios/', views.reporte_intercambios, name='reporte_intercambios'),
    path('reportes/entradas_salidas/', views.reporte_entradas_salidas, name='reporte_entradas_salidas'),
    path('gestion/insumos/', views.gestion_insumos, name='gestion_insumos'),
    path('gestion/insumos/procesar/<int:insumo_id>/', views.procesar_insumo, name='procesar_insumo'),
    path('gestion/agenda/', views.gestion_agenda, name='gestion_agenda'),

    # URLs de Guardia
    path('guardia/registro_entrada/', views.registro_entrada, name='registro_entrada'),
    path('guardia/registro_salida/', views.registro_salida, name='registro_salida'),
    path('guardia/gestion_backups/', views.guardia_gestion_backups, name='guardia_gestion_backups'),
    path('guardia/registro_backup/', views.registro_backup, name='registro_backup'),

    path('dashboard/mecanico/', views.mecanico_dashboard, name='mecanico_dashboard'),
    path('dashboard/guardia/', views.guardia_dashboard, name='guardia_dashboard'),
    path('dashboard/supervisor/', views.supervisor_dashboard, name='supervisor_dashboard'),
    path('supervisor/reportes/', views.supervisor_reportes, name='supervisor_reportes'),
    path('mantenimiento/<int:mantenimiento_id>/validar/', views.validar_reparacion, name='validar_reparacion'),
    path('seguimiento/mantenimientos/', views.seguimiento_mantenimientos, name='seguimiento_mantenimientos'),
    path('supervisor/documentos/', views.seleccionar_vehiculo_documentos, name='seleccionar_vehiculo_documentos'),
    path('supervisor/documentos/<str:patente>/', views.gestion_documentos_por_vehiculo, name='gestion_documentos_por_vehiculo'),
    path('supervisor/documentos/eliminar/<int:documento_id>/', views.eliminar_documento, name='eliminar_documento'),
    path('dashboard/jefe_taller/', views.jefe_taller_dashboard, name='jefe_taller_dashboard'),
    path('backups/', views.ver_backups, name='ver_backups'),
    path('documentos/', views.ver_documentos, name='ver_documentos'),
    path('documentos/descargar/<int:documento_id>/', views.descargar_documento, name='descargar_documento'),
    path('fotos/descargar/<int:foto_id>/', views.descargar_foto_mantenimiento, name='descargar_foto_mantenimiento'),
    path('asignar/<int:mantenimiento_id>/', views.asignar_mantenimiento, name='asignar_mantenimiento'),
    path('mantenimiento/<int:mantenimiento_id>/', views.detalle_mantenimiento, name='detalle_mantenimiento'),
    path('mantenimiento/<int:mantenimiento_id>/iniciar_pausa/', views.iniciar_pausa, name='iniciar_pausa'),
    path('mantenimiento/<int:mantenimiento_id>/terminar_pausa/', views.terminar_pausa, name='terminar_pausa'),
    path('mantenimiento/<int:mantenimiento_id>/cerrar/', views.cerrar_reparacion, name='cerrar_reparacion'),

]
