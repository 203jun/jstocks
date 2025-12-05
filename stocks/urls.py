from django.urls import path
from . import views

app_name = 'stocks'

urlpatterns = [
    path('', views.index, name='index'),
    path('stocks/', views.stock_list, name='stock_list'),
    path('stocks/<str:code>/', views.stock_detail, name='stock_detail'),
    path('stocks/<str:code>/edit/', views.stock_edit, name='stock_edit'),
    path('market/', views.market, name='market'),
    path('sector/', views.sector, name='sector'),
    path('nodaji/<int:nodaji_id>/summary/', views.nodaji_summary, name='nodaji_summary'),
    path('api/telegram/search/', views.search_telegram, name='search_telegram'),
    path('api/disclosure/search/', views.search_disclosure, name='search_disclosure'),
    path('api/report/search/', views.search_report, name='search_report'),
    path('api/nodaji/search/', views.search_nodaji, name='search_nodaji'),
    path('api/nodaji/brief/', views.fetch_nodaji_brief, name='fetch_nodaji_brief'),
    path('api/dart/<str:code>/', views.fetch_dart, name='fetch_dart'),
    path('api/schedule/<str:code>/add/', views.schedule_add, name='schedule_add'),
    path('api/schedule/<int:schedule_id>/delete/', views.schedule_delete, name='schedule_delete'),
    path('api/sector/date/', views.sector_date_data, name='sector_date_data'),
]
