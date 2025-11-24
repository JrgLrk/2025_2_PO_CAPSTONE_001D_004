# operaciones/decorators.py
from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages

def role_required(allowed_roles=[]):
    """
    Decorador para verificar si un usuario tiene uno de los roles permitidos.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            # Si el usuario no está logueado, @login_required ya lo habrá redirigido.
            # Pero por si acaso:
            if not request.user.is_authenticated:
                return redirect('login')
            
            # Si el rol del usuario NO está en la lista de roles permitidos
            if request.user.rol not in allowed_roles:
                # Redirigir a 'home' con un mensaje de error
                messages.error(request, 'No tienes permiso para acceder a esta página.')
                return redirect('home')
            
            # Si tiene el rol, ejecutar la vista normalmente
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator