from django.urls import path
from . import views

app_name = 'simulator'

urlpatterns = [
    # Landing and Authentication
    path('', views.landing_page, name='landing_page'),
    path('guide/', views.user_guide, name='user_guide'),
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    
    # Simulation Pages (Protected)
    path('simulation/', views.main_simulation, name='main_simulation'),
    path('landuse/', views.landuse_list, name='landuse_list'),
    path('landuse/<int:pk>/update_percent/', views.update_landuse_percent, name='update_landuse_percent'),
    path('landuse/<int:pk>/', views.landuse_detail, name='landuse_detail'),
    path('renewable/', views.renewable_list, name='renewable_list'),
    path('verbrauch/', views.verbrauch_view, name='verbrauch'),
    path('cockpit/', views.cockpit_view, name='cockpit'),
    path('annual-electricity/', views.annual_electricity_view, name='annual_electricity'),
    path('smard/', views.smard_solar_wind, name='smard_solar_wind'),
    path('bilanz/', views.bilanz_view, name='bilanz'),
    path('api/balance-energy/', views.balance_energy, name='balance_energy'),
    path('api/ws/balance/', views.balance_ws_storage, name='balance_ws_storage'),
    # path('usecase-diagram/', views.usecase_diagram, name='usecase_diagram'),  # Disabled - view not implemented
    
    # API Endpoints
    path('api/update-user-percent/', views.update_user_percent, name='update_user_percent'),
    path('api/update/<str:code>/', views.update_user_percent, name='update_user_percent_code'),
    path('api/save-all-inputs/', views.save_all_user_inputs, name='save_all_inputs'),
    path('api/run-full-recalc/', views.run_full_recalc_view, name='run_full_recalc'),
]
