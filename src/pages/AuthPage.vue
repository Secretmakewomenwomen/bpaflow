<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { login, register } from '../lib/auth';
import { getCurrentTenantId, listTenants, setCurrentTenantId } from '../lib/tenant';

const emit = defineEmits<{
  (event: 'authenticated'): void;
  (event: 'go-tenants'): void;
}>();

const activeTab = ref<'login' | 'register'>('login');
const submitting = ref(false);
const loadingTenants = ref(false);
const errorMessage = ref('');
const tenantId = ref(getCurrentTenantId());
const tenantOptions = ref<Array<{ label: string; value: string }>>([]);

const loginForm = reactive({
  username: '',
  password: ''
});

const registerForm = reactive({
  username: '',
  password: '',
  confirmPassword: ''
});

async function refreshTenants() {
  loadingTenants.value = true;
  try {
    const records = await listTenants();
    tenantOptions.value = records
      .filter((item) => item.enabled)
      .map((item) => ({
        label: `${item.name} (${item.tenant_id})`,
        value: item.tenant_id
      }));
    if (!tenantOptions.value.some((item) => item.value === tenantId.value) && tenantOptions.value.length > 0) {
      tenantId.value = tenantOptions.value[0].value;
      setCurrentTenantId(tenantId.value);
    }
  } catch {
    tenantOptions.value = [{ label: '默认租户 (default)', value: 'default' }];
  } finally {
    loadingTenants.value = false;
  }
}

function handleTenantChange(value: string) {
  tenantId.value = value;
  setCurrentTenantId(value);
}

async function handleLogin() {
  if (submitting.value) {
    return;
  }

  submitting.value = true;
  errorMessage.value = '';
  try {
    setCurrentTenantId(tenantId.value);
    await login(loginForm.username.trim(), loginForm.password);
    emit('authenticated');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登录失败。';
  } finally {
    submitting.value = false;
  }
}

async function handleRegister() {
  if (submitting.value) {
    return;
  }

  if (registerForm.password !== registerForm.confirmPassword) {
    errorMessage.value = '两次输入的密码不一致。';
    return;
  }

  submitting.value = true;
  errorMessage.value = '';
  try {
    setCurrentTenantId(tenantId.value);
    await register(registerForm.username.trim(), registerForm.password);
    emit('authenticated');
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '注册失败。';
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  void refreshTenants();
});
</script>

<template>
  <div class="auth-layout">
    <div class="auth-hero">
      <a-space direction="vertical" :size="20" class="auth-hero-stack">
        <a-tag color="blue" class="auth-pill">JWT Access</a-tag>
        <div>
          <h1>登录后进入专属画布</h1>
          <p class="auth-copy">
            每个账号都会绑定独立的 UUID `user_id`。上传记录、工作数据和后续画布数据都只属于当前用户。
          </p>
        </div>
        <a-space wrap>
          <a-tag>用户名 + 密码</a-tag>
          <a-tag>JWT 鉴权</a-tag>
          <a-tag>用户数据隔离</a-tag>
        </a-space>
      </a-space>
    </div>

    <a-card class="auth-card" :bordered="false">
      <template #title>
        <div class="auth-card-title">
          <span>账号认证</span>
          <small>登录或注册后进入画布工作台（按租户隔离）</small>
        </div>
      </template>

      <a-space class="auth-tenant-actions" align="center">
        <a-select
          class="auth-tenant-select"
          :value="tenantId"
          :options="tenantOptions"
          :loading="loadingTenants"
          placeholder="选择租户"
          @change="handleTenantChange"
        />
        <a-button @click="emit('go-tenants')">租户管理</a-button>
      </a-space>

      <a-alert
        v-if="errorMessage"
        class="auth-alert"
        type="error"
        show-icon
        :message="errorMessage"
      />

      <a-tabs v-model:activeKey="activeTab" class="auth-tabs">
        <a-tab-pane key="login" tab="登录">
          <a-form layout="vertical" class="auth-form" @finish="handleLogin">
            <a-form-item label="用户名" name="username">
              <a-input
                v-model:value="loginForm.username"
                size="large"
                placeholder="请输入用户名"
              />
            </a-form-item>
            <a-form-item label="密码" name="password">
              <a-input-password
                v-model:value="loginForm.password"
                size="large"
                placeholder="请输入密码"
              />
            </a-form-item>
            <a-button
              class="auth-submit"
              type="primary"
              html-type="submit"
              size="large"
              block
              :loading="submitting"
              @click="handleLogin"
            >
              登录
            </a-button>
          </a-form>
        </a-tab-pane>

        <a-tab-pane key="register" tab="注册">
          <a-form layout="vertical" class="auth-form" @finish="handleRegister">
            <a-form-item label="用户名" name="username">
              <a-input
                v-model:value="registerForm.username"
                size="large"
                placeholder="设置一个用户名"
              />
            </a-form-item>
            <a-form-item label="密码" name="password">
              <a-input-password
                v-model:value="registerForm.password"
                size="large"
                placeholder="至少 6 位"
              />
            </a-form-item>
            <a-form-item label="确认密码" name="confirmPassword">
              <a-input-password
                v-model:value="registerForm.confirmPassword"
                size="large"
                placeholder="再次输入密码"
              />
            </a-form-item>
            <a-button
              class="auth-submit"
              type="primary"
              html-type="submit"
              size="large"
              block
              :loading="submitting"
              @click="handleRegister"
            >
              注册并进入画布
            </a-button>
          </a-form>
        </a-tab-pane>
      </a-tabs>
    </a-card>
  </div>
</template>
