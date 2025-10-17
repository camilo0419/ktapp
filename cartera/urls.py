# cartera/urls.py
from django.urls import path
from . import views

app_name = "cartera"

urlpatterns = [
    path("", views.ClienteListView.as_view(), name="clientes_list"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="clientes_create"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="clientes_detail"),
    path("clientes/<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="clientes_update"),

    path("tx/nueva/", views.TransaccionCreateView.as_view(), name="tx_create"),
    path("tx/<int:pk>/editar/", views.TransaccionUpdateView.as_view(), name="tx_update"),
    path("tx/<int:pk>/pagada/", views.transaccion_marcar_pagado, name="tx_pagada"),
]
