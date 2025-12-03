from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.index, name='index'),
    path('stocks/', views.stock_list, name='stock_list'),
    path('stocks/<str:code>/', views.stock_detail, name='stock_detail'),
]
