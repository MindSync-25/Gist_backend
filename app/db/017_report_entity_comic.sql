-- Migration 017: Add comic to report_entity_type enum
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'report_entity_type'::regtype
          AND enumlabel = 'comic'
    ) THEN
        ALTER TYPE report_entity_type ADD VALUE 'comic';
    END IF;
END$$;
