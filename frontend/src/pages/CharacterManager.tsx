import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { characterApi, Character, CharacterReference } from '../api/characterApi';
import { message, Upload, Modal, Form, Input, Button, Card, Image, Space, Popconfirm } from 'antd';
import { PlusOutlined, DeleteOutlined, UploadOutlined } from '@ant-design/icons';

const { TextArea } = Input;

/**
 * 角色管理页面
 */
const CharacterManager: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [uploadingCharacterId, setUploadingCharacterId] = useState<number | null>(null);
  const [references, setReferences] = useState<Record<number, CharacterReference[]>>({});
  const [form] = Form.useForm();

  // 加载角色列表
  const loadCharacters = async () => {
    if (!projectId) return;
    
    try {
      setLoading(true);
      const response = await characterApi.listCharacters(parseInt(projectId));
      setCharacters(response.data);
      
      // 加载每个角色的参考图像
      for (const char of response.data) {
        await loadReferences(char.id);
      }
    } catch (error) {
      message.error('加载角色列表失败');
    } finally {
      setLoading(false);
    }
  };

  // 加载角色的参考图像
  const loadReferences = async (characterId: number) => {
    if (!projectId) return;
    
    try {
      const response = await characterApi.listReferences(
        parseInt(projectId),
        characterId
      );
      setReferences(prev => ({
        ...prev,
        [characterId]: response.data
      }));
    } catch (error) {
      console.error('加载参考图像失败:', error);
    }
  };

  useEffect(() => {
    loadCharacters();
  }, [projectId]);

  // 创建角色
  const handleCreate = async (values: any) => {
    if (!projectId) return;
    
    try {
      await characterApi.createCharacter(parseInt(projectId), values);
      message.success('角色创建成功');
      setModalVisible(false);
      form.resetFields();
      loadCharacters();
    } catch (error) {
      message.error('创建角色失败');
    }
  };

  // 删除角色
  const handleDelete = async (characterId: number) => {
    if (!projectId) return;
    
    try {
      await characterApi.deleteCharacter(parseInt(projectId), characterId);
      message.success('角色删除成功');
      loadCharacters();
    } catch (error) {
      message.error('删除角色失败');
    }
  };

  // 上传参考图像
  const handleUploadReference = async (file: File, characterId: number) => {
    if (!projectId) return;
    
    try {
      setUploadingCharacterId(characterId);
      await characterApi.uploadReference(
        parseInt(projectId),
        characterId,
        file,
        `参考图像 ${new Date().toLocaleString()}`
      );
      message.success('参考图像上传成功');
      await loadReferences(characterId);
    } catch (error) {
      message.error('上传参考图像失败');
    } finally {
      setUploadingCharacterId(null);
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between' }}>
        <h1>角色管理</h1>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
          创建角色
        </Button>
      </div>

      <Card loading={loading}>
        {characters.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <p>还没有角色，点击"创建角色"开始添加</p>
          </div>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size="large">
            {characters.map(character => (
              <Card
                key={character.id}
                title={character.name}
                extra={
                  <Popconfirm
                    title="确定要删除这个角色吗？"
                    onConfirm={() => handleDelete(character.id)}
                  >
                    <Button danger icon={<DeleteOutlined />} size="small">
                      删除
                    </Button>
                  </Popconfirm>
                }
              >
                <div style={{ marginBottom: 16 }}>
                  <p><strong>描述：</strong>{character.description || '无'}</p>
                  <p><strong>性格：</strong>{character.personality || '无'}</p>
                  <p><strong>外貌：</strong>{character.appearance || '无'}</p>
                </div>

                <div>
                  <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong>参考图像 ({references[character.id]?.length || 0})</strong>
                    <Upload
                      accept="image/*"
                      showUploadList={false}
                      beforeUpload={(file) => {
                        handleUploadReference(file, character.id);
                        return false;
                      }}
                    >
                      <Button 
                        icon={<UploadOutlined />} 
                        loading={uploadingCharacterId === character.id}
                      >
                        上传参考图
                      </Button>
                    </Upload>
                  </div>

                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {references[character.id]?.map(ref => (
                      <Image
                        key={ref.id}
                        src={`http://localhost:8000/static/${ref.image_path}`}
                        alt={ref.description}
                        width={100}
                        height={100}
                        style={{ objectFit: 'cover', borderRadius: 4 }}
                      />
                    ))}
                    {(!references[character.id] || references[character.id].length === 0) && (
                      <p style={{ color: '#999' }}>暂无参考图像，请上传 5-10 张清晰照片</p>
                    )}
                  </div>
                </div>
              </Card>
            ))}
          </Space>
        )}
      </Card>

      <Modal
        title="创建角色"
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={null}
      >
        <Form form={form} onFinish={handleCreate} layout="vertical">
          <Form.Item
            name="name"
            label="角色名称"
            rules={[{ required: true, message: '请输入角色名称' }]}
          >
            <Input placeholder="例如：张三" />
          </Form.Item>

          <Form.Item name="description" label="角色描述">
            <TextArea rows={3} placeholder="角色的背景故事、身份等" />
          </Form.Item>

          <Form.Item name="personality" label="性格特点">
            <Input placeholder="例如：开朗、勇敢、聪明" />
          </Form.Item>

          <Form.Item name="appearance" label="外貌特征">
            <Input placeholder="例如：黑色短发，身材高大" />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit" block>
              创建
            </Button>
          </Form.Item>
        </Form>
      </Modal>

      <Card style={{ marginTop: 24 }}>
        <h3>使用提示</h3>
        <ul>
          <li>为每个主要角色上传 5-10 张清晰的正面照片</li>
          <li>照片应包含不同角度和表情，以获得更好的效果</li>
          <li>系统会自动使用 IP-Adapter 确保角色面部一致性</li>
          <li>参考图像质量越高，生成效果越好</li>
        </ul>
      </Card>
    </div>
  );
};

export default CharacterManager;
