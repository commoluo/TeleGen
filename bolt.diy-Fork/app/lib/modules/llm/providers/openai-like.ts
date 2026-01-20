import { BaseProvider, getOpenAILikeModel } from '~/lib/modules/llm/base-provider';
import type { ModelInfo } from '~/lib/modules/llm/types';
import type { IProviderSetting } from '~/types/model';
import type { LanguageModelV1 } from 'ai';

export default class OpenAILikeProvider extends BaseProvider {
  name = 'OpenAILike';
  getApiKeyLink = undefined;

  config = {
    baseUrlKey: 'OPENAI_LIKE_API_BASE_URL',
    apiTokenKey: 'OPENAI_LIKE_API_KEY',
  };

  staticModels: ModelInfo[] = [
    {
      name: '/mnt/cache/sharemath/models/qwen/Qwen2.5-Coder-32B-Instruct',
      label: 'Qwen2.5-Coder-32B-Instruct',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'deepseek-v3-250324',
      label: 'deepseek-v3-250324',
      provider: 'OpenAILike',
      maxTokenAllowed: 16384,
    },
    {
      name: 'deepseek-r1-250120',
      label: 'deepseek-r1-250120',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gemini-2.0-pro-exp',
      label: 'gemini-2.0-pro-exp',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gemini-2.0-flash',
      label: 'gemini-2.0-flash',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'o3-mini',
      label: 'o3-mini',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gpt-4.5-preview',
      label: 'gpt-4.5-preview',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gpt-4',
      label: 'gpt-4',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gpt-4o',
      label: 'gpt-4o',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'gpt-4o',
      label: 'gpt-4o',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'deepseek-r1-250120',
      label: 'deepseek-r1-250120',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'claude-3-5-sonnet-20240620',
      label: 'claude-3-5-sonnet-20240620',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
    {
      name: 'claude-3-5-sonnet-20241022',
      label: 'claude-3-5-sonnet-20241022',
      provider: 'OpenAILike',
      maxTokenAllowed: 8000,
    },
  ];

  async getDynamicModels(
    apiKeys?: Record<string, string>,
    settings?: IProviderSetting,
    serverEnv: Record<string, string> = {},
  ): Promise<ModelInfo[]> {
    const { baseUrl, apiKey } = this.getProviderBaseUrlAndKey({
      apiKeys,
      providerSettings: settings,
      serverEnv,
      defaultBaseUrlKey: 'OPENAI_LIKE_API_BASE_URL',
      defaultApiTokenKey: 'OPENAI_LIKE_API_KEY',
    });

    if (!baseUrl || !apiKey) {
      return [];
    }

    const response = await fetch(`${baseUrl}/models`, {
      headers: {
        Authorization: `Bearer ${apiKey}`,
      },
    });

    const res = (await response.json()) as any;

    return res.data.map((model: any) => ({
      name: model.id,
      label: model.id,
      provider: this.name,
      maxTokenAllowed: 8000,
    }));
  }

  getModelInstance(options: {
    model: string;
    serverEnv: Env;
    apiKeys?: Record<string, string>;
    providerSettings?: Record<string, IProviderSetting>;
  }): LanguageModelV1 {
    const { model, serverEnv, apiKeys, providerSettings } = options;

    const { baseUrl, apiKey } = this.getProviderBaseUrlAndKey({
      apiKeys,
      providerSettings: providerSettings?.[this.name],
      serverEnv: serverEnv as any,
      defaultBaseUrlKey: 'OPENAI_LIKE_API_BASE_URL',
      defaultApiTokenKey: 'OPENAI_LIKE_API_KEY',
    });

    if (!baseUrl || !apiKey) {
      throw new Error(`Missing configuration for ${this.name} provider`);
    }

    return getOpenAILikeModel(baseUrl, apiKey, model);
  }
}
