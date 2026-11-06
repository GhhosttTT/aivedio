import { describe, expect, it } from 'vitest';
import { prepareShotSpecification } from './shotSpecification';

describe('shot specification save contract', () => {
    it('preserves direction and removes obsolete states without mutating the draft', () => {
        const draft = {purpose: 'confrontation', camera_intensity: 'low' as const,
            continuity_constraints: [' wet coat ', ''],
            character_states: [{character_name: 'Alice', start_state: 'right hand holds knife'}, {character_name: 'Bob'}]};
        const result = prepareShotSpecification(draft, ['Alice']);
        expect(result).toEqual({...draft, continuity_constraints: ['wet coat'], character_states: [draft.character_states[0]]});
        expect(draft.character_states).toHaveLength(2);
        expect(draft.continuity_constraints).toEqual([' wet coat ', '']);
    });
    it('keeps explicit clearing', () => {
        expect(prepareShotSpecification(null, [])).toBeNull();
    });
    it('normalizes structured continuity assets without adding them to legacy specs', () => {
        const result = prepareShotSpecification({
            continuity_assets: [{
                asset_id: ' prop:knife ', kind: 'prop' as const,
                start_state: {hand: ' right ', empty: ' '}, end_state: {holder: ' Alice '},
            }],
        }, []);
        expect(result?.continuity_assets).toEqual([{
            asset_id: 'prop:knife', kind: 'prop',
            start_state: {hand: ' right '}, end_state: {holder: ' Alice '}, transition_note: '',
        }]);
        expect(prepareShotSpecification({purpose: 'legacy'}, [])).toEqual({
            purpose: 'legacy', continuity_constraints: [], character_states: [],
        });
    });
    it('rejects blank or duplicate structured continuity asset IDs', () => {
        expect(() => prepareShotSpecification({continuity_assets: [{asset_id: ' '}]} as any, [])).toThrow();
        expect(() => prepareShotSpecification({continuity_assets: [{asset_id: 'prop:key'}, {asset_id: 'prop:key'}]} as any, [])).toThrow();
    });
    it.each([NaN, Infinity, 0, -1, 121])('rejects invalid duration %s', duration => {
        expect(() => prepareShotSpecification({duration_seconds: duration}, [])).toThrow();
    });
    it.each([0, 1.5, 6])('rejects invalid performance intensity %s', intensity => {
        expect(() => prepareShotSpecification({performance_intensity: intensity}, [])).toThrow();
    });
    it('normalizes explicit local driving assets', () => {
        expect(prepareShotSpecification({
            motion_reference_video: ' D:\\assets\\walk.mp4 ',
            performance_reference_audio: ' D:\\assets\\line.wav ',
        }, [])).toMatchObject({
            motion_reference_video: 'D:\\assets\\walk.mp4',
            performance_reference_audio: 'D:\\assets\\line.wav',
        });
    });
    it('deduplicates and preserves explicit engine capability requirements', () => {
        expect(prepareShotSpecification({
            shot_role: 'dialogue_reaction',
            required_engine_capabilities: ['identity_reference', 'performance_control', 'identity_reference'],
        }, [])).toMatchObject({
            shot_role: 'dialogue_reaction',
            required_engine_capabilities: ['identity_reference', 'performance_control'],
        });
        expect(() => prepareShotSpecification({
            required_engine_capabilities: ['unknown_control' as any],
        }, [])).toThrow('未知');
    });
});
