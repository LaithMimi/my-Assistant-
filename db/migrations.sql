-- Supabase migration: agent_logs table for CEO Assistant evaluation hooks
-- Run this once in your Supabase project SQL editor.

CREATE TABLE IF NOT EXISTS agent_logs (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL,

    -- Shared fields
    event_type      TEXT NOT NULL,                  -- 'tool_call' | 'agent_run'
    chat_id         TEXT NOT NULL,                  -- Telegram chat_id as string
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error           TEXT,
    latency_ms      NUMERIC(10, 2),

    -- tool_call fields
    tool_name       TEXT,
    tool_input      TEXT,
    tool_output     TEXT,

    -- agent_run fields
    user_input      TEXT,
    final_output    TEXT,
    tools_used      TEXT[]                          -- array of tool names invoked
);

-- Indexes for analytics queries
CREATE INDEX IF NOT EXISTS idx_agent_logs_chat_id     ON agent_logs(chat_id);
CREATE INDEX IF NOT EXISTS idx_agent_logs_event_type  ON agent_logs(event_type);
CREATE INDEX IF NOT EXISTS idx_agent_logs_tool_name   ON agent_logs(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_logs_created_at  ON agent_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_logs_success      ON agent_logs(success);

-- Useful analytics views -------------------------------------------------------

-- Most-used tools (for optimisation)
CREATE OR REPLACE VIEW tool_usage_stats AS
SELECT
    tool_name,
    COUNT(*)                            AS total_calls,
    ROUND(AVG(latency_ms)::numeric, 0) AS avg_latency_ms,
    SUM(CASE WHEN success THEN 0 ELSE 1 END) AS failures
FROM agent_logs
WHERE event_type = 'tool_call' AND tool_name IS NOT NULL
GROUP BY tool_name
ORDER BY total_calls DESC;

-- Command usage frequency (from user_input prefix)
CREATE OR REPLACE VIEW command_usage_stats AS
SELECT
    SPLIT_PART(user_input, ' ', 1) AS command,
    COUNT(*)                        AS uses,
    ROUND(AVG(latency_ms)::numeric, 0) AS avg_latency_ms
FROM agent_logs
WHERE event_type = 'agent_run'
GROUP BY 1
ORDER BY uses DESC;
