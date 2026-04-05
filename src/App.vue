<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AuthPage from './pages/AuthPage.vue';
import CanvasPage from './pages/CanvasPage.vue';
import { authState, clearAuth, hasToken, restoreAuthState } from './lib/auth';

const currentPath = ref(window.location.pathname);

const isAuthenticated = computed(() => hasToken() && Boolean(authState.user));

function navigate(path: '/login' | '/canvas', replace = false) {
  if (replace) {
    window.history.replaceState({}, '', path);
  } else {
    window.history.pushState({}, '', path);
  }
  currentPath.value = path;
}

function syncRoute() {
  if (isAuthenticated.value) {
    if (currentPath.value === '/' || currentPath.value === '/login') {
      navigate('/canvas', true);
    }
    return;
  }

  if (currentPath.value !== '/login') {
    navigate('/login', true);
  }
}

async function handleAuthSuccess() {
  navigate('/canvas');
}

async function handleLogout() {
  clearAuth();
  navigate('/login');
}

function handlePopState() {
  currentPath.value = window.location.pathname;
  syncRoute();
}

onMounted(async () => {
  if (hasToken()) {
    await restoreAuthState();
  }
  syncRoute();
  window.addEventListener('popstate', handlePopState);
});

watch(
  () => authState.token,
  () => {
    syncRoute();
  }
);

onBeforeUnmount(() => {
  window.removeEventListener('popstate', handlePopState);
});
</script>

<template>
  <CanvasPage v-if="isAuthenticated" @logout="handleLogout" />
  <AuthPage v-else @authenticated="handleAuthSuccess" />
</template>
