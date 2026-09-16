/**
 * 角色管理 API
 */

import apiClient from '../api/client';

export interface Character {
  id: number;
  name: string;
  description?: string;
  personality?: string;
  appearance?: string;
}

export interface CharacterReference {
  id: number;
  character_id: number;
  image_path: string;
  description?: string;
}

export interface CharacterIdentityPlan {
  character_id: number;
  identity_spec: Record<string, any>;
  prompt_pack: Record<string, any>;
  distinctiveness: Record<string, any>;
}

export interface CharacterIdentityScore {
  character_id: number;
  status: string;
  average: number;
  scores: Record<string, {score: number; evidence: string}>;
  limitation: string;
}

export interface CharacterReferenceGeneration {
  character_id: number;
  reference: CharacterReference;
  candidate_images: string[];
  quality_report: Record<string, any>;
}

export const characterApi = {
  /**
   * 创建角色
   */
  createCharacter: async (projectId: number, data: Omit<Character, 'id'>) => {
    return apiClient.post<Character>(`/projects/${projectId}/characters`, data);
  },

  /**
   * 获取项目的所有角色
   */
  listCharacters: async (projectId: number) => {
    return apiClient.get<never, Character[]>(`/projects/${projectId}/characters`);
  },

  /**
   * 获取角色详情
   */
  getCharacter: async (projectId: number, characterId: number) => {
    return apiClient.get<Character>(`/projects/${projectId}/characters/${characterId}`);
  },

  /**
   * 删除角色
   */
  deleteCharacter: async (projectId: number, characterId: number) => {
    return apiClient.delete<{ message: string }>(`/projects/${projectId}/characters/${characterId}`);
  },

  /**
   * 上传角色参考图像
   */
  uploadReference: async (
    projectId: number,
    characterId: number,
    file: File,
    description?: string
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    if (description) {
      formData.append('description', description);
    }

    return apiClient.post<CharacterReference>(
      `/projects/${projectId}/characters/${characterId}/reference`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    );
  },

  /**
   * 获取角色的所有参考图像
   */
  listReferences: async (projectId: number, characterId: number) => {
    return apiClient.get<never, CharacterReference[]>(
      `/projects/${projectId}/characters/${characterId}/references`
    );
  },

  planIdentity: async (projectId: number, characterId: number, targetLanguages?: string[]) => {
    return apiClient.post<any, CharacterIdentityPlan>(
      `/projects/${projectId}/characters/${characterId}/identity-plan`,
      { target_languages: targetLanguages, update_character: true }
    );
  },

  scoreIdentity: async (projectId: number, characterId: number, observedSpec: Record<string, any>) => {
    return apiClient.post<any, CharacterIdentityScore>(
      `/projects/${projectId}/characters/${characterId}/identity-score`,
      { observed_spec: observedSpec }
    );
  },

  generateReference: async (projectId: number, characterId: number, count = 3) => {
    return apiClient.post<any, CharacterReferenceGeneration>(
      `/projects/${projectId}/characters/${characterId}/generate-reference`,
      { count }
    );
  },
};
