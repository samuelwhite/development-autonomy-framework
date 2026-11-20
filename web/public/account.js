'use strict';

{
  const get = (id) => document.getElementById(id);
  const loginPath = '/login';
  const userSettings = location.pathname === '/settings/users';
  const roleName = (role) => role === 'administrator' ? 'Administrator' : 'Viewer';
  const goToLogin = () => location.replace(loginPath);

  function el(tag, value, className) {
    const node = document.createElement(tag);
    if (value) node.textContent = value;
    if (className) node.className = className;
    return node;
  }

  async function api(path, data) {
    const options = { cache: 'no-store' };
    if (data !== undefined) {
      options.method = 'POST';
      options.headers = { 'Content-Type': 'application/json' };
      options.body = JSON.stringify(data);
    }
    const response = await fetch(path, options);
    const body = await response.json().catch(() => null);
    if (!response.ok || !body) {
      const error = Error(body?.error || 'Mission Control could not complete the request.');
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function bind(form, submit, after, signedIn = true) {
    const message = form.querySelector('[role="alert"]');
    const button = form.querySelector('button[type="submit"]');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (button.disabled) return;
      const data = Object.fromEntries(new FormData(form));
      delete data.show;
      message.textContent = '';
      button.disabled = true;
      try {
        await submit(data);
        form.reset();
        for (const field of form.querySelectorAll('[autocomplete$="password"]')) field.type = 'password';
        await after();
      } catch (error) {
        if (signedIn && error.status === 401) goToLogin();
        else message.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  }

  document.addEventListener('change', (event) => {
    if (!event.target.matches('[data-show-password]')) return;
    for (const field of event.target.form.querySelectorAll('[autocomplete$="password"]')) {
      field.type = event.target.checked ? 'text' : 'password';
    }
  });

  function userRow(user, lastAdmin) {
    const item = el('li');
    const top = el('div', null, 'row');
    top.append(el('h3', user.username, 'account-name'), el('span', user.enabled ? 'Enabled' : 'Disabled', 'badge'));
    item.append(top, el('p', roleName(user.role), 'meta'));
    const actions = el('div', null, 'user-actions');
    const toggle = el('button', user.enabled ? 'Disable' : 'Enable', 'action');
    toggle.type = 'button';
    toggle.setAttribute('aria-label', `${toggle.textContent} ${user.username}`);
    toggle.disabled = lastAdmin;
    const error = el('p', null, 'form-error');
    error.setAttribute('role', 'alert');
    toggle.addEventListener('click', async () => {
      toggle.disabled = true;
      error.textContent = '';
      try {
        await api('/api/users/status', { username: user.username, enabled: !user.enabled });
        await loadUsers(`${user.username} ${user.enabled ? 'disabled' : 'enabled'}.`);
      } catch (failure) {
        if (failure.status === 401) goToLogin();
        else error.textContent = failure.message;
        toggle.disabled = false;
      }
    });
    actions.append(toggle);
    if (lastAdmin) actions.append(el('span', 'Last enabled administrator', 'note'));
    item.append(actions, error);

    const reset = el('details');
    const summary = el('summary', 'Reset password');
    summary.setAttribute('aria-label', `Reset password for ${user.username}`);
    const form = el('form', null, 'account-form');
    form.method = 'post';
    const label = el('label', 'New password');
    const input = el('input');
    input.type = 'password';
    input.name = 'password';
    input.autocomplete = 'new-password';
    input.required = true;
    input.minLength = 10;
    label.append(input);
    const visibility = el('label', null, 'checkbox');
    const check = el('input');
    check.type = 'checkbox';
    check.setAttribute('data-show-password', '');
    visibility.append(check, 'Show password');
    const submit = el('button', 'Set password', 'action');
    submit.type = 'submit';
    const message = el('p', null, 'form-error');
    message.setAttribute('role', 'alert');
    form.append(label, visibility, submit, message);
    bind(form, ({ password }) => api('/api/users/reset-password', { username: user.username, password }),
      () => loadUsers(`Password reset for ${user.username}.`));
    reset.append(summary, form);
    item.append(reset);
    return item;
  }

  async function loadUsers(message = '') {
    const users = await api('/api/users');
    const list = get('users-list');
    const replaceFocusedRow = list.contains(document.activeElement);
    const adminCount = users.filter((user) => user.enabled && user.role === 'administrator').length;
    list.replaceChildren(...users.map((user) => userRow(user,
      adminCount === 1 && user.enabled && user.role === 'administrator')));
    const status = get('users-status');
    status.textContent = message || `${users.length} local accounts`;
    if (replaceFocusedRow) {
      status.tabIndex = -1;
      status.focus();
    }
  }

  async function setupAccount() {
    const nav = get('session-tools');
    if (!nav) return;
    try {
      const user = await api('/api/account');
      nav.hidden = false;
      get('settings-link').hidden = user.role !== 'administrator';
      for (const link of nav.querySelectorAll('a')) {
        if (link.pathname === location.pathname) link.setAttribute('aria-current', 'page');
      }
      get('logout').addEventListener('click', async () => {
        try {
          await api('/api/account/logout', {});
          goToLogin();
        } catch (error) {
          get('session-error').textContent = error.message;
        }
      });
      if (userSettings) {
        document.title = 'Users · DAF Mission Control';
        get('user-settings').hidden = false;
        bind(get('create-user'), (data) => api('/api/users/create', data), () => loadUsers('User added.'));
        await loadUsers();
      } else if (get('my-account')) {
        get('my-account').hidden = false;
        get('account-identity').textContent = `${user.username} · ${roleName(user.role)}`;
        bind(get('change-password'), (data) => api('/api/account/password', data), goToLogin);
      }
    } catch (error) {
      if (error.status === 401) goToLogin();
      else if (get('account-error')) get('account-error').textContent = error.message;
    }
  }

  if (get('login-form')) {
    bind(get('login-form'), (data) => api('/api/account/login', data), () => location.replace('/'), false);
  } else {
    void setupAccount();
  }
}
