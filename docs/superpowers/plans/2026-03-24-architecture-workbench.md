# Architecture Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working version of a single-user architecture document workbench with a dark, restrained UI, a central mxGraph canvas, and swimlane support.

**Architecture:** Create a Vue 3 + Rsbuild application with a thin application shell, a dedicated graph workspace component, and focused stores/types for palette data and inspector state. Seed the canvas with a sample architecture board so the product is immediately usable and visually coherent.

**Tech Stack:** Vue 3, TypeScript, pnpm, Rsbuild, mxGraph, CSS variables

---

### Task 1: Scaffold The Project

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `rsbuild.config.ts`
- Create: `index.html`
- Create: `src/main.ts`
- Create: `src/App.vue`
- Create: `src/env.d.ts`

- [ ] **Step 1: Write the package and TypeScript config**
- [ ] **Step 2: Add the Rsbuild entrypoints**
- [ ] **Step 3: Mount the Vue application**

### Task 2: Build The Workbench Shell

**Files:**
- Create: `src/styles/base.css`
- Create: `src/styles/workbench.css`
- Create: `src/components/AppHeader.vue`
- Create: `src/components/DocumentRail.vue`
- Create: `src/components/InspectorPanel.vue`
- Modify: `src/App.vue`

- [ ] **Step 1: Define the dark design tokens and page chrome**
- [ ] **Step 2: Add the three-column workbench layout**
- [ ] **Step 3: Populate the rail and inspector with architecture-oriented content**

### Task 3: Integrate mxGraph Canvas

**Files:**
- Create: `src/lib/mxgraph.ts`
- Create: `src/components/ArchitectureCanvas.vue`
- Create: `src/data/seedDocument.ts`

- [ ] **Step 1: Initialize mxGraph safely in Vue**
- [ ] **Step 2: Seed the canvas with swimlanes, services, and edges**
- [ ] **Step 3: Add lightweight toolbar actions for zoom and fit**

### Task 4: Verification

**Files:**
- Modify: `package.json`

- [ ] **Step 1: Install dependencies with pnpm**
- [ ] **Step 2: Run a production build**
- [ ] **Step 3: Document any environment gaps if verification is blocked**
