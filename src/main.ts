import { createApp } from 'vue';
import Antd from 'ant-design-vue';
import App from './App.vue';
import 'ant-design-vue/dist/reset.css';
import './styles/auth.css';
import './styles/base.css';
import './styles/workbench.css';

createApp(App).use(Antd).mount('#root');
