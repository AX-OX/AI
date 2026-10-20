-- Apply only if you already installed the earlier AX Navigator schema.
-- On a fresh database use 00_schema_postgres16.sql + 01_seed_input_postgres.sql instead.
-- This is a role-free MVP migration; the approval actor is the authenticated requester.
BEGIN;
ALTER TABLE users DROP COLUMN IF EXISTS role;
UPDATE users SET email='analyst1@gaon.example', user_name='가상 AX 분석 담당자'
 WHERE user_id=601 AND email='admin@gaon.example';
UPDATE users SET email='analyst2@gaon.example'
 WHERE user_id=602 AND email='member@gaon.example';
-- Fix ONLY the packaged demo approval. Never rewrite real-world approval histories.
UPDATE ax_roadmaps AS r SET approved_by=t.user_id
 FROM ai_tasks AS t
 WHERE r.task_id=t.task_id AND r.roadmap_id=801
   AND r.task_id='66580f0c-445d-5d0d-a5a4-45ef6c3f5d56'
   AND r.approval_status='APPROVED';
COMMIT;
