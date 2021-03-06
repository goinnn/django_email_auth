# -*- encoding: utf-8 -*-

import datetime
import urlparse

from base64 import encodestring, decodestring

from django.conf import settings
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render_to_response
from django.utils.translation import ugettext as _
from django.utils.encoding import iri_to_uri
from django.views.decorators.cache import never_cache
from django.contrib.sites.models import Site, RequestSite
from django.template import RequestContext
from django.dispatch import Signal

from email_auth.forms import AuthenticationForm

user_logged_in = Signal(providing_args=['request'])
user_logged_out = Signal(providing_args=['request'])


def login(request, template_name='registration/login.html',
          authentication_form=AuthenticationForm,
          redirect_field_name=REDIRECT_FIELD_NAME,
          extra_context=None):
    """
    Displays the login form, handles the email-based login action.
    May set a "remember me" cookie.
    Adapted from django.contrib.auth.views.login
    """
    redirect_to = request.REQUEST.get(redirect_field_name, '')
    if request.method == "POST":
        form = authentication_form(data=request.POST)
        if form.is_valid():
            netloc = urlparse.urlparse(redirect_to)[1]

            # Use default setting if redirect_to is empty
            if not redirect_to:
                redirect_to = settings.LOGIN_REDIRECT_URL

            # Heavier security check -- don't allow redirection to a different
            # host.
            elif netloc and netloc != request.get_host():
                redirect_to = settings.LOGIN_REDIRECT_URL

            return email_login(request,
                               form.get_user(),
                               form.cleaned_data['email'],
                               form.cleaned_data['password'],
                               form.cleaned_data['remember'],
                               redirect_to=redirect_to)
    else:
        # get login cookie if any
        if 'django_email_auth' in request.COOKIES:
            cookie_data = decodestring(request.COOKIES['django_email_auth'])
            try:
                e, p = cookie_data.split(':')
            except ValueError:
                e, p = (None, None)
            form = authentication_form(request,
                    {'email': e, 'password': p, 'remember': True})
        else:
            form = authentication_form(request)
    request.session.set_test_cookie()
    if Site._meta.installed:
        current_site = Site.objects.get_current()
    else:
        current_site = RequestSite(request)
    context = {
        'form': form,
        redirect_field_name: redirect_to,
        'site': current_site,
        'site_name': current_site.name,
    }
    if extra_context is not None:
        context.update(extra_context)
    return render_to_response(template_name, context, context_instance=RequestContext(request))
login = never_cache(login)


def email_login(request, user, email, password, remember, redirect_to=None):
    if not hasattr(user, 'backend'):
        user.backend = 'email_auth.backends.EmailBackend'
    from django.contrib.auth import login
    login(request, user)
    if request.session.test_cookie_worked():
        request.session.delete_test_cookie()

    response = HttpResponse()
    # handle "remember me" cookie
    # effacer le cookie s'il existe
    response.delete_cookie('django_email_auth')
    if remember:
        try:
            cookie_data = encodestring('%s:%s' % (email, password))
            max_age = 30 * 24 * 60 * 60
            expires = datetime.datetime.strftime(
                datetime.datetime.utcnow() +
                datetime.timedelta(seconds=max_age),
                "%a, %d-%b-%Y %H:%M:%S GMT"
                )
            response.set_cookie('django_email_auth',
                    cookie_data, max_age=max_age, expires=expires)
        except UnicodeEncodeError:
            pass
    # send signal "user just logged in"
    user_logged_in.send(sender=request.user, request=request)
    # retourner à la vue appelante
    response.status_code = 302
    if redirect_to:
        response['Location'] = iri_to_uri(redirect_to)
    else:
        response['Location'] = settings.LOGIN_REDIRECT_URL
    return response


def logout(request, next_page=None,
           template_name='registration/logged_out.html',
           redirect_field_name=REDIRECT_FIELD_NAME,
           extra_context=None):
    """
    Logs out the user and displays 'You are logged out' message.
    Sends the user_logged_out signal.
    """
    from django.contrib.auth import logout
    user_was = request.user
    logout(request)
    user_logged_out.send(sender=user_was, request=request)
    if next_page is None:
        redirect_to = request.REQUEST.get(redirect_field_name, '')
        if redirect_to:
            return HttpResponseRedirect(redirect_to)
        else:
            context = {
                'title': _('Logged out')
            }
            if extra_context is not None:
                context.update(extra_context)
            return render_to_response(template_name,
                                      context,
                                      context_instance=RequestContext(request))
    else:
        # Redirect to this page until the session has been cleared.
        return HttpResponseRedirect(next_page or request.path)
