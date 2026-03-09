from django.urls import path
from . import views

urlpatterns = [
    path('mark_workbooks/', views.mark_workbooks, name='mark_workbooks'),
    # ...other url patterns...
]
