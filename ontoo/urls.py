from django.urls import path

from . import views

app_name = 'ontoo'

urlpatterns = [
    path('', views.index, name='index'),
    path('stock/<str:code>/', views.stock_detail, name='stock_detail'),
    path('research/<int:report_id>/', views.research_detail, name='research_detail'),
    path('api/dart-document/<str:rcept_no>/', views.dart_document, name='dart_document'),
]
