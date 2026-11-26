from django.urls import path

from catalog.api import views

urlpatterns = [
    path("allergens/", views.AllergenListView.as_view(), name="allergen-list"),
    path("articles/", views.ArticleListView.as_view(), name="article-list"),
    path("articles/import/", views.ArticleImportView.as_view(), name="article-import"),
    path("articles/<uuid:pk>/", views.ArticleDetailView.as_view(), name="article-detail"),
    path("articles/<uuid:pk>/conversions/", views.ConversionListView.as_view(), name="article-conversions"),
    path("partners/", views.PartnerListView.as_view(), name="partner-list"),
    path("partners/cities/", views.PartnerCityListView.as_view(), name="partner-cities"),
    path("partners/import/", views.PartnerImportView.as_view(), name="partner-import"),
    path("partners/<uuid:pk>/", views.PartnerDetailView.as_view(), name="partner-detail"),
]
