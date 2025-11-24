# operaciones/middleware.py
from django.utils.cache import add_never_cache_headers

class NoCacheMiddleware:
    """
    Middleware para añadir cabeceras 'Cache-Control: no-store' a las respuestas
    para usuarios autenticados. Esto previene que el navegador guarde en caché
    páginas protegidas, evitando que se puedan ver al presionar "Atrás"
    después de cerrar sesión.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Procesar la petición y obtener la respuesta de la vista
        response = self.get_response(request)

        # Si el usuario está autenticado, añadir las cabeceras para no cachear
        if request.user.is_authenticated:
            add_never_cache_headers(response)
            
        return response