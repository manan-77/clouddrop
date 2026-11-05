// @ts-check
const { defineConfig } = require('eslint/config');
const eslint = require('@eslint/js');
const tseslint = require('typescript-eslint');
const angular = require('angular-eslint');

const PROMISES = 'Promises cannot be cancelled or torn down with the component. Stay in RxJS.';
const SECURITY_SYNTAX = [
  {
    selector: 'MemberExpression[property.name=/^(innerHTML|outerHTML)$/]',
    message: 'No raw HTML injection.',
  },
  {
    selector: 'MemberExpression[property.name=/^bypassSecurityTrust/]',
    message: 'Never bypass Angular sanitising.',
  },
  { selector: "CallExpression[callee.name='eval']", message: 'No eval.' },
  { selector: "NewExpression[callee.name='Function']", message: 'No new Function.' },
  {
    selector: "MemberExpression[object.name='document'][property.name='write']",
    message: 'No document.write.',
  },
];
const PROMISE_SYNTAX = [
  { selector: 'AwaitExpression', message: PROMISES },
  { selector: ':function[async=true]', message: PROMISES },
  { selector: 'CallExpression[callee.name=/^(firstValueFrom|lastValueFrom)$/]', message: PROMISES },
  { selector: "MemberExpression[property.name='toPromise']", message: PROMISES },
];

const DEEP_RELATIVE = {
  group: ['../../../*'],
  message: 'Use the @core, @shared or @features aliases.',
};
const FEATURES = {
  group: ['@features/*', '**/features/**'],
  message: 'Layering: only features may import from features, and never each other.',
};
const SHARED = { group: ['@shared/*'], message: 'Layering: core must not import shared.' };

module.exports = defineConfig([
  {
    files: ['**/*.ts'],
    extends: [
      eslint.configs.recommended,
      tseslint.configs.recommended,
      tseslint.configs.stylistic,
      angular.configs.tsRecommended,
    ],
    processor: angular.processInlineTemplates,
    rules: {
      '@angular-eslint/directive-selector': [
        'error',
        { type: 'attribute', prefix: 'cd', style: 'camelCase' },
      ],
      '@angular-eslint/component-selector': [
        'error',
        { type: ['element', 'attribute'], prefix: 'cd', style: 'kebab-case' },
      ],
      '@angular-eslint/prefer-on-push-component-change-detection': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { fixStyle: 'inline-type-imports', disallowTypeAnnotations: false },
      ],
      'no-console': 'error',
      'no-restricted-syntax': ['error', ...SECURITY_SYNTAX, ...PROMISE_SYNTAX],
      'no-restricted-imports': ['error', { patterns: [DEEP_RELATIVE] }],
    },
  },
  {
    // Layering: features -> shared, core. shared -> core. core -> nothing above it.
    files: ['src/app/shared/**/*.ts'],
    rules: { 'no-restricted-imports': ['error', { patterns: [DEEP_RELATIVE, FEATURES] }] },
  },
  {
    files: ['src/app/core/**/*.ts'],
    rules: { 'no-restricted-imports': ['error', { patterns: [DEEP_RELATIVE, FEATURES, SHARED] }] },
  },
  {
    files: ['src/app/features/**/*.ts'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            DEEP_RELATIVE,
            { group: ['@features/*'], message: 'Features must not import each other.' },
          ],
        },
      ],
    },
  },
  {
    // Angular's own testing API is promise based (whenStable); the security bans still apply.
    files: ['**/*.spec.ts'],
    rules: { 'no-restricted-syntax': ['error', ...SECURITY_SYNTAX] },
  },
  {
    files: ['**/*.html'],
    extends: [angular.configs.templateRecommended, angular.configs.templateAccessibility],
    rules: {},
  },
]);
