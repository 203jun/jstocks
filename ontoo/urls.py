from django.urls import path

from . import views

app_name = 'ontoo'

urlpatterns = [
    path('', views.index, name='index'),
]
