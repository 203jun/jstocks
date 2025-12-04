from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.index, name='index'),
    path('stocks/', views.stock_list, name='stock_list'),
    path('stocks/<str:code>/', views.stock_detail, name='stock_detail'),
    path('stocks/<str:code>/edit/', views.stock_edit, name='stock_edit'),
    path('api/telegram/search/', views.search_telegram, name='search_telegram'),
    path('api/disclosure/search/', views.search_disclosure, name='search_disclosure'),
    path('api/report/search/', views.search_report, name='search_report'),
    path('api/nodaji/search/', views.search_nodaji, name='search_nodaji'),
]
