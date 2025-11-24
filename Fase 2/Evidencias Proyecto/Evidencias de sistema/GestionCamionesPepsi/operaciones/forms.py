# operaciones/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import Mantenimiento, Vehiculo, Agenda_Taller, Documento, Usuario, Sitio, Insumo, FotoMantenimiento, Pausa, Taller, Observacion

class DocumentoForm(forms.ModelForm):
    class Meta:
        model = Documento
        fields = ['vehiculo', 'nombre_documento', 'archivo', 'fecha_vencimiento']
        widgets = {
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'nombre_documento': forms.TextInput(attrs={'class': 'form-control'}),
            'archivo': forms.FileInput(attrs={'class': 'form-control'}),
            'fecha_vencimiento': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'},
                format='%Y-%m-%d'
            ),
        }

class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = UserCreationForm.Meta.fields + ('first_name', 'last_name', 'email', 'rol', 'especialidad')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Hacemos que el campo username no sea requerido en el formulario, ya que lo generaremos automáticamente.
        if 'username' in self.fields:
            self.fields['username'].required = False

    def _generate_username(self, first_name, last_name):
        # Elimina espacios y convierte a minúsculas
        first_name = first_name.lower().replace(' ', '')
        last_name = last_name.lower().replace(' ', '')
        
        # Intenta con la primera letra del nombre + apellido
        base_username = f"{first_name[0]}{last_name}"
        return base_username

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get('rol')
        especialidad = cleaned_data.get('especialidad')
        if rol == Usuario.Roles.MECANICO and not especialidad:
            self.add_error('especialidad', 'Los mecánicos deben tener una especialidad.')
        if rol != Usuario.Roles.MECANICO and especialidad:
            cleaned_data['especialidad'] = None
        return cleaned_data

    def save(self, commit=True):
        # Sobrescribimos el método save para generar el username
        user = super().save(commit=False)
        
        first_name = self.cleaned_data.get('first_name', '')
        last_name = self.cleaned_data.get('last_name', '')

        if first_name and last_name:
            base_username = self._generate_username(first_name, last_name)
            username = base_username
            num = 1
            # Buscamos un username único
            while Usuario.objects.filter(username=username).exists():
                # Si ya existe, intentamos con más letras del nombre
                if len(first_name) > num:
                    username = f"{first_name[:num+1]}{last_name.lower().replace(' ', '')}"
                else: # Si se acabaron las letras, añadimos un número
                    username = f"{base_username}{num - len(first_name) + 1}"
                num += 1
            user.username = username

        if commit:
            # La contraseña se establece aquí solo en la creación
            password = self.cleaned_data.get("password")
            user.set_password(password)
            user.save()
        return user

class CustomUserChangeForm(UserChangeForm):

    def clean(self):
        cleaned_data = super().clean()
        rol = cleaned_data.get('rol')
        especialidad = cleaned_data.get('especialidad')
        if rol == Usuario.Roles.MECANICO and not especialidad:
            self.add_error('especialidad', 'Los mecánicos deben tener una especialidad.')
        if rol != Usuario.Roles.MECANICO and especialidad:
            cleaned_data['especialidad'] = None
        return cleaned_data

    # Hacemos que la contraseña no sea requerida para la edición
    password = None
    new_password1 = forms.CharField(
        label="Nueva contraseña",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        required=False,
        help_text="Deje en blanco para no cambiar la contraseña."
    )
    new_password2 = forms.CharField(
        label="Confirmación de nueva contraseña",
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        required=False
    )

    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = ('username', 'first_name', 'last_name', 'email', 'rol', 'especialidad', 'is_active')

    def clean_new_password2(self):
        new_password1 = self.cleaned_data.get("new_password1")
        new_password2 = self.cleaned_data.get("new_password2")
        if new_password1 and new_password1 != new_password2:
            raise forms.ValidationError(
                self.error_messages['password_mismatch'],
                code='password_mismatch',
            )
        return new_password2

class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ['patente', 'marca', 'modelo', 'año', 'chofer_asignado', 'sitio', 'es_backup', 'estado_actual']

class SitioForm(forms.ModelForm):
    class Meta:
        model = Sitio
        fields = ['nombre_sitio']
        widgets = {
            'nombre_sitio': forms.TextInput(attrs={'class': 'form-control'}),
        }

class AsignarBackupForm(forms.Form):
    chofer = forms.ModelChoiceField(
        queryset=Usuario.objects.filter(rol=Usuario.Roles.CHOFER, is_active=True),
        label="Asignar a Chofer",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    vehiculo_patente = forms.CharField(widget=forms.HiddenInput())

class GeneradorAgendaForm(forms.Form):
    DIAS_SEMANA = [
        (0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'),
        (3, 'Jueves'), (4, 'Viernes'), (5, 'Sábado'), (6, 'Domingo'),
    ]

    MODO_GENERACION = [
        ('slots', 'Slots de duración fija'),
        ('bloques', 'Bloques de Mañana/Tarde'),
    ]

    taller = forms.ModelChoiceField(
        queryset=Taller.objects.all(),
        label="Seleccione el Taller",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    tipo_atencion = forms.ChoiceField(
        choices=Agenda_Taller.TipoAtencion.choices,
        label="Tipo de Atención para los Slots",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    fecha_inicio = forms.DateField(
        label="Desde la fecha",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    fecha_fin = forms.DateField(
        label="Hasta la fecha",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    dias_semana = forms.MultipleChoiceField(
        choices=DIAS_SEMANA,
        label="En los días",
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    hora_apertura = forms.TimeField(
        label="Desde las",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    hora_cierre = forms.TimeField(
        label="Hasta las",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    duracion_slot = forms.IntegerField(
        label="Duración de cada slot (en minutos)",
        min_value=15,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        required=False
    )
    modo_generacion = forms.ChoiceField(
        choices=MODO_GENERACION,
        label="Modo de Generación",
        widget=forms.RadioSelect, initial='slots'
    )
    hora_inicio_colacion = forms.TimeField(
        label="Inicio de Colación",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        required=False
    )
    duracion_colacion = forms.IntegerField(
        label="Duración de colación (minutos)",
        min_value=0, initial=60,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )

class EliminadorAgendaForm(forms.Form):
    taller = forms.ModelChoiceField(
        queryset=Taller.objects.all(),
        label="Seleccione el Taller",
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    fecha_inicio = forms.DateField(
        label="Eliminar desde la fecha",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        required=True
    )
    fecha_fin = forms.DateField(
        label="Eliminar hasta la fecha",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        required=True
    )
    tipo_atencion = forms.ChoiceField(
        choices=[('', 'Todas las especialidades')] + Agenda_Taller.TipoAtencion.choices,
        label="Especialidad a eliminar (opcional)",
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=False
    )

class DiagnosticoForm(forms.ModelForm):
    class Meta:
        model = Mantenimiento
        fields = ['diagnostico', 'trabajo_realizado']
        widgets = {
            'diagnostico': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'trabajo_realizado': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'diagnostico': 'Diagnóstico del Mecánico',
            'trabajo_realizado': 'Trabajo Realizado',
        }

class InsumoForm(forms.ModelForm):
    class Meta:
        model = Insumo
        fields = ['nombre_insumo', 'cantidad']
        widgets = {
            'nombre_insumo': forms.TextInput(attrs={'class': 'form-control'}),
            'cantidad': forms.NumberInput(attrs={'class': 'form-control'}),
        }

class FotoMantenimientoForm(forms.ModelForm):
    class Meta:
        model = FotoMantenimiento
        fields = ['imagen', 'descripcion']

class PausaForm(forms.ModelForm):
    class Meta:
        model = Pausa
        fields = ['motivo']




class MantenimientoSolicitudForm(forms.ModelForm):

    agenda_slot = forms.IntegerField(
        widget=forms.HiddenInput(),
        required=True
    )
    
    class Meta:
        model = Mantenimiento
        fields = ['vehiculo', 'motivo_ingreso']
        widgets = {
            'vehiculo': forms.Select(attrs={'class': 'form-select'}),
            'motivo_ingreso': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
        labels = {
            'vehiculo': 'Mi Vehículo (Patente)',
            'motivo_ingreso': 'Descripción del Problema',
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if user:
            self.fields['vehiculo'].queryset = Vehiculo.objects.filter(chofer_asignado=user)
            if self.fields['vehiculo'].queryset.count() == 1:
                self.fields['vehiculo'].initial = self.fields['vehiculo'].queryset.first()