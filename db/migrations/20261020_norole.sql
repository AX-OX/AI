-- 기존 공통 스키마용. 실행 전 백업·검토. 원래 승인 이력을 임의로 만들지 않는다.
BEGIN;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS access_level VARCHAR(20);
UPDATE documents SET access_level=CASE WHEN document_id=403 THEN 'CONFIDENTIAL' ELSE 'INTERNAL' END WHERE access_level IS NULL;
ALTER TABLE documents ALTER COLUMN access_level SET NOT NULL;
ALTER TABLE ax_roadmaps ADD COLUMN IF NOT EXISTS approved_by BIGINT REFERENCES users(user_id);
ALTER TABLE users DROP COLUMN IF EXISTS role;
UPDATE users SET email='analyst1@gaon.example', user_name='가상 AX 분석 담당자' WHERE user_id=601 AND email='admin@gaon.example';
UPDATE users SET email='analyst2@gaon.example' WHERE user_id=602 AND email='member@gaon.example';
COMMIT;
