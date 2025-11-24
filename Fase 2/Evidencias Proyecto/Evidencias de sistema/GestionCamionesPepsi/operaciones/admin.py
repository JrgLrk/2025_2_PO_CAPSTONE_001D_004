from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from .models import (
    Usuario, Sitio, Taller, Vehiculo, Mantenimiento,
    Documento, FotoMantenimiento, Observacion, Pausa,
    Agenda_Taller, Insumo, Historial_Cambios
)


#Formulario personalizado para validación
class UsuarioForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get('rol')
        especialidad = cleaned_data.get('especialidad')

        # Validación: los mecánicos deben tener especialidad
        if rol == Usuario.Roles.MECANICO and not especialidad:
            self.add_error('especialidad', 'Los mecánicos deben tener una especialidad definida.')

        # Limpia la especialidad si no es mecánico
        if rol != Usuario.Roles.MECANICO:
            cleaned_data['especialidad'] = None

        return cleaned_data


#Configuración del admin
class CustomUserAdmin(UserAdmin):
    form = UsuarioForm

    list_display = ('username', 'email', 'first_name', 'last_name', 'rol', 'especialidad', 'is_staff')
    list_filter = ('rol', 'is_staff', 'is_superuser', 'is_active')

    fieldsets = UserAdmin.fieldsets + (
        ('Rol y Especialidad', {'fields': ('rol', 'especialidad')}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Rol y Especialidad', {
            'classes': ('wide',),
            'fields': ('rol', 'especialidad'),
        }),
    )

    #Inyectar JS para ocultar dinámicamente el campo
    class Media:
        js = ('admin/js/hide_especialidad.js',)


#Registro de modelos
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Vehiculo)
admin.site.register(Mantenimiento)
admin.site.register(Documento)
admin.site.register(FotoMantenimiento)
admin.site.register(Observacion)
admin.site.register(Pausa)
admin.site.register(Sitio)
admin.site.register(Taller)
admin.site.register(Agenda_Taller)
admin.site.register(Insumo)
admin.site.register(Historial_Cambios)
