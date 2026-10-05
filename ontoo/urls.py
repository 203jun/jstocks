from django.urls import path

from . import views

app_name = 'ontoo'

urlpatterns = [
    path('', views.index, name='index'),
    path('stock/<str:code>/', views.stock_detail, name='stock_detail'),
]
