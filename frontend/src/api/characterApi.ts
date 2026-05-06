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

export const characterApi = {
  /**
   * 创建角色
   */
  createCharacter: async (projectId: number, data: Omit<Character, 'id'>) => {
    return apiClient.post<Character>(`/api/projects/${projectId}/characters`, data);
  },

  /**
   * 获取项目的所有角色
   */
  listCharacters: async (projectId: number) => {
    return apiClient.get<Character[]>(`/api/projects/${projectId}/characters`);
  },

  /**
   * 获取角色详情
   */
  getCharacter: async (projectId: number, characterId: number) => {
    return apiClient.get<Character>(`/api/projects/${projectId}/characters/${characterId}`);
  },

  /**
   * 删除角色
   */
  deleteCharacter: async (projectId: number, characterId: number) => {
    return apiClient.delete<{ message: string }>(`/api/projects/${projectId}/characters/${characterId}`);
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
      `/api/projects/${projectId}/characters/${characterId}/reference`,
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
    return apiClient.get<CharacterReference[]>(
      `/api/projects/${projectId}/characters/${characterId}/references`
    );
  },
};
