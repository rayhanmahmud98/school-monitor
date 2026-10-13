def role_context(request):
    """Expose `role` and the matching base template to every template."""
    user = request.user
    if user.is_authenticated:
        return {"role": user.role, "base_template": f"base_{user.role.lower()}.html"}
    return {"role": None, "base_template": "base_public.html"}
