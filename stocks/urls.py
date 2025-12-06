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
    path('etf/', views.etf, name='etf'),
    path('etf/<str:code>/', views.etf_detail, name='etf_detail'),
    path('api/etf/add/', views.add_etf, name='add_etf'),
    path('api/etf/save/', views.save_etf, name='save_etf'),
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
    path('settings/', views.settings, name='settings'),
    path('api/category/add/', views.category_add, name='category_add'),
    path('api/category/<int:category_id>/delete/', views.category_delete, name='category_delete'),
    path('api/theme/add/', views.theme_add, name='theme_add'),
    path('api/theme/<int:theme_id>/delete/', views.theme_delete, name='theme_delete'),
    path('api/news/search/', views.search_google_news, name='search_google_news'),
]
