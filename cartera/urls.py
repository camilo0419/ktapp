from django.urls import path
from . import views

app_name = "cartera"

urlpatterns = [
    # INICIO
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard_alias"),  # opcional

    # CLIENTES
    path("clientes/", views.ClienteListView.as_view(), name="clientes_list"),
    path("clientes/nuevo/", views.ClienteCreateView.as_view(), name="clientes_create"),
    path("clientes/<int:pk>/", views.ClienteDetailView.as_view(), name="clientes_detail"),
    path("clientes/<int:pk>/editar/", views.ClienteUpdateView.as_view(), name="clientes_update"),

    # TRANSACCIONES
    path("tx/nueva/", views.TransaccionCreateView.as_view(), name="tx_create"),
    path("tx/<int:pk>/editar/", views.TransaccionUpdateView.as_view(), name="tx_update"),
    path("tx/<int:pk>/pagada/", views.transaccion_marcar_pagado, name="tx_pagada"),

    # ABONOS
    path("tx/<int:tx_id>/abono/nuevo/", views.AbonoCreateView.as_view(), name="abono_create"),
    path("abono/<int:pk>/eliminar/", views.abono_delete, name="abono_delete"),
]
