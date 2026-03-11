from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BillFolderViewSet, BillViewSet

router = DefaultRouter()
router.register('folders', BillFolderViewSet, basename='bill-folder')
router.register('', BillViewSet, basename='bill')
urlpatterns = [path('', include(router.urls))]
