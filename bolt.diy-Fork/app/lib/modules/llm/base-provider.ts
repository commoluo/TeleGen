import type { LanguageModelV1 } from 'ai';
import type { ProviderInfo, ProviderConfig, ModelInfo } from './types';
import type { IProviderSetting } from '~/types/model';
import { createOpenAI } from '@ai-sdk/openai';
import { LLMManager } from './manager';

export abstract class BaseProvider implements ProviderInfo {
  abstract name: string;
  abstract staticModels: ModelInfo[];
  abstract config: ProviderConfig;
  cachedDynamicModels?: {
    cacheId: string;
    models: ModelInfo[];
  };

  getApiKeyLink?: string;
  labelForGetApiKey?: string;
  icon?: string;

  getProviderBaseUrlAndKey(options: {
    apiKeys?: Record<string, string>;
    providerSettings?: IProviderSetting;
    serverEnv?: Record<string, string>;
    defaultBaseUrlKey: string;
    defaultApiTokenKey: string;
  }) {
    const { apiKeys, providerSettings, serverEnv, defaultBaseUrlKey, defaultApiTokenKey } = options;
    let settingsBaseUrl = providerSettings?.baseUrl;
    const manager = LLMManager.getInstance();

    if (settingsBaseUrl && settingsBaseUrl.length == 0) {
      settingsBaseUrl = undefined;
    }

    const baseUrlKey = this.config.baseUrlKey || defaultBaseUrlKey;
    let baseUrl =
      settingsBaseUrl ||
      serverEnv?.[baseUrlKey] ||
      process?.env?.[baseUrlKey] ||
      manager.env?.[baseUrlKey] ||
      this.config.baseUrl;

    if (baseUrl && baseUrl.endsWith('/')) {
      baseUrl = baseUrl.slice(0, -1);
    }

    const apiTokenKey = this.config.apiTokenKey || defaultApiTokenKey;
    const apiKey =
      apiKeys?.[this.name] || serverEnv?.[apiTokenKey] || process?.env?.[apiTokenKey] || manager.env?.[apiTokenKey];

    return {
      baseUrl,
      apiKey,
    };
  }
  getModelsFromCache(options: {
    apiKeys?: Record<string, string>;
    providerSettings?: Record<string, IProviderSetting>;
    serverEnv?: Record<string, string>;
  }): ModelInfo[] | null {
    if (!this.cachedDynamicModels) {
      // console.log('no dynamic models',this.name);
      return null;
    }

    const cacheKey = this.cachedDynamicModels.cacheId;
    const generatedCacheKey = this.getDynamicModelsCacheKey(options);

    if (cacheKey !== generatedCacheKey) {
      // console.log('cache key mismatch',this.name,cacheKey,generatedCacheKey);
      this.cachedDynamicModels = undefined;
      return null;
    }

    return this.cachedDynamicModels.models;
  }
  getDynamicModelsCacheKey(options: {
    apiKeys?: Record<string, string>;
    providerSettings?: Record<string, IProviderSetting>;
    serverEnv?: Record<string, string>;
  }) {
    return JSON.stringify({
      apiKeys: options.apiKeys?.[this.name],
      providerSettings: options.providerSettings?.[this.name],
      serverEnv: options.serverEnv,
    });
  }
  storeDynamicModels(
    options: {
      apiKeys?: Record<string, string>;
      providerSettings?: Record<string, IProviderSetting>;
      serverEnv?: Record<string, string>;
    },
    models: ModelInfo[],
  ) {
    const cacheId = this.getDynamicModelsCacheKey(options);

    // console.log('caching dynamic models',this.name,cacheId);
    this.cachedDynamicModels = {
      cacheId,
      models,
    };
  }

  // Declare the optional getDynamicModels method
  getDynamicModels?(
    apiKeys?: Record<string, string>,
    settings?: IProviderSetting,
    serverEnv?: Record<string, string>,
  ): Promise<ModelInfo[]>;

  abstract getModelInstance(options: {
    model: string;
    serverEnv?: Env;
    apiKeys?: Record<string, string>;
    providerSettings?: Record<string, IProviderSetting>;
  }): LanguageModelV1;
}

type OptionalApiKey = string | undefined;

// Custom fetch function to handle non-standard API response formats
function createCustomFetch(originalFetch = fetch) {
  return async (url: string | URL | Request, init?: RequestInit) => {
    const response = await originalFetch(url, init);
    
    // Only process chat completions requests
    if (url.toString().includes('/chat/completions') && response.ok) {
      const contentType = response.headers.get('content-type');
      
      if (contentType?.includes('application/json')) {
        // Read the response body
        const originalText = await response.text();
        
        try {
          // Parse the JSON
          const data = JSON.parse(originalText);
          
          // Transform the response to match OpenAI format
          if (data && typeof data === 'object') {
            // Convert created field from string to number if needed
            if (data.created && typeof data.created === 'string') {
              // Try to parse the date string and convert to Unix timestamp
              try {
                const date = new Date(data.created);
                data.created = Math.floor(date.getTime() / 1000);
              } catch {
                // If parsing fails, use current timestamp
                data.created = Math.floor(Date.now() / 1000);
              }
            }
            
            // Ensure other required fields are present
            if (!data.id && data.id !== '') {
              data.id = `chatcmpl-${Date.now()}`;
            }
            
            if (!data.object) {
              data.object = 'chat.completion';
            }
            
            if (!data.model && data.model !== '') {
              data.model = 'gpt-4';
            }
            
            // Ensure choices array exists and has proper format
            if (data.choices && Array.isArray(data.choices)) {
              data.choices = data.choices.map((choice: any, index: number) => ({
                index: choice.index !== undefined ? choice.index : index,
                message: choice.message || choice.delta || {},
                finish_reason: choice.finish_reason || 'stop',
                ...choice,
              }));
            }
            
            // Ensure usage object exists
            if (!data.usage) {
              data.usage = {
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
              };
            }
          }
          
          // Create a new response with the transformed data
          return new Response(JSON.stringify(data), {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers,
          });
        } catch {
          // If JSON parsing fails, return original response
          return new Response(originalText, {
            status: response.status,
            statusText: response.statusText,
            headers: response.headers,
          });
        }
      }
    }
    
    return response;
  };
}

export function getOpenAILikeModel(baseURL: string, apiKey: OptionalApiKey, model: string) {
  const openai = createOpenAI({
    baseURL,
    apiKey,
    fetch: createCustomFetch(),
  });

  return openai(model);
}
