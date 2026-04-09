<script setup lang="ts">
import { message } from 'ant-design-vue';
import { onMounted, reactive, ref } from 'vue';
import { createTenant, listTenants, setCurrentTenantId } from '../lib/tenant';
import type { TenantRecord } from '../types/tenant';

const emit = defineEmits<{
  (event: 'back'): void;
}>();

const loading = ref(false);
const submitting = ref(false);
const errorMessage = ref('');
const tenants = ref<TenantRecord[]>([]);
const form = reactive({
  tenantId: '',
  name: '',
  databaseName: '',
  databaseUrl: '',
  configJson: '{}'
});

async function refreshTenants() {
  loading.value = true;
  errorMessage.value = '';
  try {
    tenants.value = await listTenants();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '租户列表加载失败。';
  } finally {
    loading.value = false;
  }
}

async function handleCreateTenant() {
  if (submitting.value) {
    return;
  }

  let parsedConfig: Record<string, unknown> | undefined;
  const rawConfig = form.configJson.trim();
  if (rawConfig) {
    try {
      parsedConfig = JSON.parse(rawConfig) as Record<string, unknown>;
    } catch {
      errorMessage.value = '配置 JSON 格式不正确。';
      return;
    }
  }

  submitting.value = true;
  errorMessage.value = '';
  try {
    const databaseUrl = form.databaseUrl.trim();
    const databaseName = form.databaseName.trim();
    const created = await createTenant({
      tenant_id: form.tenantId.trim(),
      name: form.name.trim(),
      ...(databaseUrl ? { database_url: databaseUrl } : {}),
      ...(databaseName ? { database_name: databaseName } : {}),
      config: parsedConfig
    });
    setCurrentTenantId(created.tenant_id);
    form.tenantId = '';
    form.name = '';
    form.databaseName = '';
    form.databaseUrl = '';
    form.configJson = '{}';
    await refreshTenants();
    message.success(`租户已创建并切换：${created.tenant_id}`);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '租户创建失败。';
  } finally {
    submitting.value = false;
  }
}

onMounted(() => {
  void refreshTenants();
});
</script>

<template>
  <div class="tenant-page">
    <a-page-header title="租户管理" sub-title="租户独立 PostgreSQL 数据库" @back="emit('back')" />

    <a-row :gutter="24">
      <a-col :xs="24" :lg="10">
        <a-card title="新增租户" class="tenant-card">
          <a-alert v-if="errorMessage" type="error" show-icon :message="errorMessage" class="tenant-alert" />
          <a-form layout="vertical" :model="form" @finish="handleCreateTenant">
            <a-form-item label="租户 ID" name="tenantId">
              <a-input
                v-model:value="form.tenantId"
                placeholder="例如: tenant_a"
                :disabled="submitting"
              />
            </a-form-item>
            <a-form-item label="租户名称" name="name">
              <a-input
                v-model:value="form.name"
                placeholder="例如: 租户A"
                :disabled="submitting"
              />
            </a-form-item>
            <a-form-item label="数据库名（可选）" name="databaseName">
              <a-input
                v-model:value="form.databaseName"
                placeholder="留空自动按租户ID生成，例如 tenant_tenant_a"
                :disabled="submitting"
              />
            </a-form-item>
            <a-form-item label="PostgreSQL URL（可选）" name="databaseUrl">
              <a-input
                v-model:value="form.databaseUrl"
                placeholder="不填则后端自动建库并生成 URL"
                :disabled="submitting"
              />
            </a-form-item>
            <a-form-item label="租户配置(JSON，可选)" name="configJson">
              <a-textarea
                v-model:value="form.configJson"
                :rows="4"
                :disabled="submitting"
              />
            </a-form-item>
            <a-button
              type="primary"
              html-type="submit"
              :loading="submitting"
              block
              @click="handleCreateTenant"
            >
              创建租户
            </a-button>
          </a-form>
        </a-card>
      </a-col>

      <a-col :xs="24" :lg="14">
        <a-card title="租户列表" class="tenant-card">
          <a-table
            :data-source="tenants"
            :loading="loading"
            :pagination="false"
            row-key="tenant_id"
            size="small"
          >
            <a-table-column title="租户 ID" data-index="tenant_id" key="tenant_id" />
            <a-table-column title="名称" data-index="name" key="name" />
            <a-table-column title="状态" key="enabled">
              <template #default="{ record }">
                <a-tag :color="record.enabled ? 'green' : 'default'">
                  {{ record.enabled ? '启用' : '停用' }}
                </a-tag>
              </template>
            </a-table-column>
            <a-table-column title="数据库" data-index="database_url" key="database_url" />
          </a-table>
        </a-card>
      </a-col>
    </a-row>
  </div>
</template>
