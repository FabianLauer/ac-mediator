from django.conf import settings
from django.conf.urls import include, url
from django.contrib import admin
from django.contrib.auth import views as auth_views
from accounts.views import registration, activate_account, resend_activation_emmil
from ac_mediator.views import monitor, crash_me
from django.contrib.staticfiles.urls import staticfiles_urlpatterns


urlpatterns = [
    url(r'^crash/$', crash_me, name='crash_me'),

    # Auth urls
    url(r'^register/$', registration, name='registration'),
    url(r'^activate/(?P<username>[^\/]+)/(?P<uid_hash>[^\/]+)/.*$', activate_account, name="accounts-activate"),
    url(r'^reactivate/$', resend_activation_emmil, name="accounts-resend-activation"),
    url(r'^login/$', auth_views.login, {'template_name': 'accounts/login.html'}, name='login'),
    url(r'^logout/$', auth_views.logout, {'next_page': settings.LOGOUT_URL}, name='logout'),
    url(r'^password_reset/$', auth_views.password_reset, dict(
            template_name='accounts/password_reset_form.html',
            subject_template_name='emails/password_reset_subject.txt',
            email_template_name='emails/password_reset.txt',
        ), name='password_reset'),
    url(r'^password_reset/done/$', auth_views.password_reset_done, dict(
            template_name='accounts/password_reset_done.html'
        ), name='password_reset_done'),
    url(r'^reset/(?P<uidb64>[0-9A-Za-z_\-]+)/(?P<token>[0-9A-Za-z]{1,13}-[0-9A-Za-z]{1,20})/$',
        auth_views.password_reset_confirm, dict(
            template_name='accounts/password_reset_confirm.html'
        ), name='password_reset_confirm'),
    url(r'^reset/done/$', auth_views.password_reset_complete, dict(
            template_name='accounts/password_reset_complete.html'
        ), name='password_reset_complete'),

    # Accounts
    url(r'^', include('accounts.urls')),

    # Developers
    url(r'^developers/', include('developers.urls')),

    # Api
    url(r'^api/', include('api.urls')),

    # Admin
    url(r'^admin/monitor/$', monitor, name="admin-monitor"),
    url(r'^admin/', admin.site.urls),

    # Documentation
    url(r'^docs/', include('docs.urls')),
]

if settings.DEBUG:
    # We need to explicitly add staticfiles urls because we don't use runserver
    # https://docs.djangoproject.com/en/1.10/ref/contrib/staticfiles/#django.contrib.staticfiles.urls.staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
