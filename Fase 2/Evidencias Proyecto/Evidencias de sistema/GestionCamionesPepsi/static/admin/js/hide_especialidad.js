document.addEventListener('DOMContentLoaded', function() {
    const rolSelect = document.querySelector('#id_rol');
    const especialidadField = document.querySelector('.form-row.field-especialidad, .form-group.field-especialidad');

    function toggleEspecialidad() {
        if (!rolSelect || !especialidadField) return;
        const isMecanico = rolSelect.value === 'MECANICO';
        especialidadField.style.display = isMecanico ? '' : 'none';
    }

    if (rolSelect) {
        rolSelect.addEventListener('change', toggleEspecialidad);
        toggleEspecialidad(); // Ejecutar al cargar la página
    }
});
