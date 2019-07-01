import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.tokens import default_token_generator
from django.core.files.base import ContentFile
from django.core.urlresolvers import reverse_lazy
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.cache import cache_control
from django.views.generic import FormView, CreateView

from datacenterlight.utils import get_cms_integration
from hosting.forms import UserHostingKeyForm
from hosting.models import UserHostingKey
from membership.models import CustomUser
from opennebula_api.models import OpenNebulaManager
from utils.hosting_utils import get_all_public_keys
from .forms import SetPasswordForm
from .mailer import BaseEmail


class SignupViewMixin(CreateView):
    model = CustomUser
    success_url = None

    def get_success_url(self):
        next_url = self.request.POST.get('next') if self.request.POST.get(
            'next') \
            else self.success_url

        return next_url

    def form_valid(self, form):
        name = form.cleaned_data.get('name')
        email = form.cleaned_data.get('email')
        password = form.cleaned_data.get('password')

        CustomUser.register(name, password, email)
        auth_user = authenticate(email=email, password=password)
        login(self.request, auth_user)

        return HttpResponseRedirect(self.get_success_url())


class LoginViewMixin(FormView):
    success_url = None

    def get_success_url(self):
        next_url = self.request.POST.get('next', self.success_url)
        if not next_url:
            return self.success_url
        return next_url

    def form_valid(self, form):
        email = form.cleaned_data.get('email')
        password = form.cleaned_data.get('password')
        auth_user = authenticate(email=email, password=password)

        if auth_user:
            login(self.request, auth_user)
            return HttpResponseRedirect(self.get_success_url())

        return HttpResponseRedirect(self.get_success_url())

    @cache_control(no_cache=True, must_revalidate=True, no_store=True)
    def get(self, request, *args, **kwargs):
        if self.request.user.is_authenticated():
            return HttpResponseRedirect(self.get_success_url())

        return super(LoginViewMixin, self).get(request, *args, **kwargs)


class ResendActivationLinkViewMixin(FormView):
    success_message = _(
        "An email with the activation link has been sent to you")

    def generate_email_context(self, user):
        context = {
            'base_url': "{0}://{1}".format(self.request.scheme,
                                           self.request.get_host()),
            'activation_link': reverse_lazy(
                'hosting:validate',
                kwargs={'validate_slug': user.validation_slug}
            ),
            'dcl_text': settings.DCL_TEXT,
        }
        return context

    def form_valid(self, form):
        email = form.cleaned_data.get('email')
        user = CustomUser.objects.get(email=email)
        messages.add_message(self.request, messages.SUCCESS,
                             self.success_message)
        context = self.generate_email_context(user)
        email_data = {
            'subject': '{dcl_text} {account_activation}'.format(
                dcl_text=settings.DCL_TEXT,
                account_activation=_('Account Activation')
            ),
            'to': email,
            'context': context,
            'template_name': self.email_template_name,
            'template_path': self.email_template_path,
            'from_address': settings.DCL_SUPPORT_FROM_ADDRESS
        }
        email = BaseEmail(**email_data)
        email.send()
        return HttpResponseRedirect(self.get_success_url())


class PasswordResetViewMixin(FormView):
    success_message = _(
        "The link to reset your password has been sent to your email")
    site = ''

    def test_generate_email_context(self, user):
        context = {
            'user': user,
            'token': default_token_generator.make_token(user),
            'uid': urlsafe_base64_encode(force_bytes(user.pk)),
            'site_name': 'ungleich' if self.site != 'dcl' else settings.DCL_TEXT,
            'base_url': "{0}://{1}".format(self.request.scheme,
                                           self.request.get_host())
        }
        return context

    def form_valid(self, form):
        email = form.cleaned_data.get('email')
        user = CustomUser.objects.get(email=email)
        messages.add_message(self.request, messages.SUCCESS,
                             self.success_message)
        context = self.test_generate_email_context(user)
        email_data = {
            'subject': _('Password Reset'),
            'to': email,
            'context': context,
            'template_name': 'password_reset_email',
            'template_path': self.template_email_path
        }
        if self.site == 'dcl':
            email_data['from_address'] = settings.DCL_SUPPORT_FROM_ADDRESS
        email = BaseEmail(**email_data)
        email.send()

        return HttpResponseRedirect(self.get_success_url())


class PasswordResetConfirmViewMixin(FormView):
    form_class = SetPasswordForm

    def post(self, request, uidb64=None, token=None, *arg, **kwargs):
        try:
            uid = urlsafe_base64_decode(uidb64)
            user = CustomUser.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
            user = None

        form = self.form_class(request.POST)

        if user is not None and default_token_generator.check_token(user,
                                                                    token):
            if form.is_valid():
                new_password = form.cleaned_data['new_password2']
                user.set_password(new_password)
                user.save()
                messages.success(request, _('Password has been reset.'))
                return self.form_valid(form)
            else:
                messages.error(request,
                               _('Password reset has not been successful.'))
                form.add_error(None,
                               _('Password reset has not been successful.'))
                return self.form_invalid(form)

        else:
            messages.error(request,
                           _('The reset password link is no longer valid.'))
            form.add_error(None,
                           _('The reset password link is no longer valid.'))
            return self.form_invalid(form)


class SSHKeyCreateView(FormView):
    form_class = UserHostingKeyForm
    model = UserHostingKey
    template_name = 'hosting/user_key.html'
    login_url = reverse_lazy('hosting:login')
    context_object_name = "virtual_machine"
    success_url = reverse_lazy('hosting:ssh_keys')

    def get_form_kwargs(self):
        kwargs = super(SSHKeyCreateView, self).get_form_kwargs()
        kwargs.update({'request': self.request})
        return kwargs

    def form_valid(self, form):
        form.save()
        if settings.DCL_SSH_KEY_NAME_PREFIX in form.instance.name:
            content = ContentFile(form.cleaned_data.get('private_key'))
            filename = form.cleaned_data.get(
                'name') + '_' + str(uuid.uuid4())[:8] + '_private.pem'
            form.instance.private_key.save(filename, content)
        context = self.get_context_data()

        next_url = self.request.session.get(
            'next',
            reverse_lazy('hosting:create_virtual_machine')
        )

        if 'next' in self.request.session:
            context.update({
                'next_url': next_url
            })
            del (self.request.session['next'])

        if form.cleaned_data.get('private_key'):
            context.update({
                'private_key': form.cleaned_data.get('private_key'),
                'key_name': form.cleaned_data.get('name'),
                'form': UserHostingKeyForm(request=self.request),
            })

        owner = self.request.user
        manager = OpenNebulaManager(
            email=owner.email,
            password=owner.password
        )
        keys_to_save = get_all_public_keys(self.request.user)
        manager.save_key_in_opennebula_user('\n'.join(keys_to_save))
        return HttpResponseRedirect(self.success_url)

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        required = 'add_ssh' in self.request.POST
        form.fields['name'].required = required
        form.fields['public_key'].required = required
        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)


class AskSSHKeyView(SSHKeyCreateView):
    form_class = UserHostingKeyForm
    template_name = "datacenterlight/add_ssh_key.html"
    success_url = reverse_lazy('datacenterlight:order_confirmation')
    context_object_name = "dcl_vm_buy_add_ssh_key"

    @cache_control(no_cache=True, must_revalidate=True, no_store=True)
    def get(self, request, *args, **kwargs):
        context = {
            'site_url': reverse_lazy('datacenterlight:index'),
            'cms_integration': get_cms_integration('default'),
            'form': UserHostingKeyForm(request=self.request),
            'keys': get_all_public_keys(self.request.user)
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        self.success_url = self.request.session.get("order_confirm_url")
        return super(AskSSHKeyView, self).post(self, request, *args, **kwargs)