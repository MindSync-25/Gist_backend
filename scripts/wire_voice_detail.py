filepath = r"C:\Users\rajan\OneDrive\Desktop\GIST\Gist_frontend\app\(tabs)\voice-detail\[id].tsx"
with open(filepath, encoding="utf-8") as f:
    lines = f.readlines()

# ─── Block 1: New imports (replaces lines 1–15, 0-indexed 0–14) ───────────────
NEW_IMPORTS = """\
import { Ionicons } from '@expo/vector-icons';
import { useLocalSearchParams, usePathname, useRouter } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
\tPlatform,
\tPressable,
\tScrollView,
\tShare,
\tStyleSheet,
\tText,
\tTextInput,
\tView,
\tuseWindowDimensions,
} from 'react-native';
import { Screen } from '@/components/common/Screen';
import { useVoiceIssue, useVoiceTakes, useSetStance, useCreateTake } from '@/features/voice/hooks';
import type { VoiceIssue as ApiVoiceIssue, VoiceTake as ApiVoiceTake, VoiceTakeReply as ApiVoiceTakeReply } from '@/features/voice/types';
"""  # Note: no trailing newline since lines[15] starts the types section

# ─── Block 2: Replace ISSUE_LIBRARY (lines 106–226, 0-indexed 105–225) ────────
#             with mappers
MAPPERS = """\
function formatRelativeTime(isoString: string): string {
\tconst diffMs = Date.now() - new Date(isoString).getTime();
\tconst mins = Math.floor(diffMs / 60000);
\tif (mins < 60) return `${mins}m`;
\tconst hrs = Math.floor(mins / 60);
\tif (hrs < 24) return `${hrs}h`;
\treturn `${Math.floor(hrs / 24)}d`;
}

function mapApiReply(r: ApiVoiceTakeReply): VoiceReply {
\treturn {
\t\tid: String(r.id),
\t\tauthor: r.author,
\t\tcontent: r.content,
\t\tcreatedAt: formatRelativeTime(r.created_at),
\t\treplies: [],
\t};
}

function mapApiTake(t: ApiVoiceTake): VoiceTake {
\treturn {
\t\tid: String(t.id),
\t\tauthor: t.author,
\t\tstance: t.stance ?? undefined,
\t\tcontent: t.content,
\t\tcreatedAt: formatRelativeTime(t.created_at),
\t\treactions: t.reactions_count,
\t\treplies: t.replies.map(mapApiReply),
\t};
}

function mapApiIssue(apiIssue: ApiVoiceIssue): VoiceIssue {
\tconst nonTrending = apiIssue.tags.filter((t) => t !== 'Trending');
\treturn {
\t\tid: String(apiIssue.id),
\t\ttitle: apiIssue.title,
\t\tsummary: apiIssue.context,
\t\tcategory: nonTrending[0] ?? apiIssue.tags[0] ?? 'Voice',
\t\ttopic: nonTrending[1] ?? nonTrending[0] ?? 'India',
\t\tcreator: 'Gist',
\t\tcreatedAt: formatRelativeTime(apiIssue.created_at),
\t\tsupportCount: apiIssue.support_count,
\t\topposeCount: apiIssue.oppose_count,
\t\tquestionCount: apiIssue.question_count,
\t\ttotalEngagement: apiIssue.reacting_now,
\t\ttakes: [],
\t};
}

"""

# ─── Block 3: New VoiceDetailScreen setup (replaces lines 227–299, 0-indexed 226–298) ─
NEW_SCREEN_SETUP = """\
export default function VoiceDetailScreen() {
\tconst router = useRouter();
\tconst pathname = usePathname();
\tconst { width } = useWindowDimensions();
\tconst isDesktopWeb = Platform.OS === 'web' && width >= 1024;

\tconst params = useLocalSearchParams<{ id?: string | string[] }>();
\tconst issueId = Number(Array.isArray(params.id) ? params.id[0] : params.id ?? '0');

\tconst [activeFilter, setActiveFilter] = useState<VoiceFilter>('all');

\t// API data
\tconst { data: apiIssue } = useVoiceIssue(issueId);
\tconst { data: apiTakes } = useVoiceTakes(issueId, activeFilter);
\tconst stanceMutation = useSetStance();
\tconst createTakeMutation = useCreateTake(issueId);

\t// Build issue from API data; placeholder while loading
\tconst issue: VoiceIssue = apiIssue ? mapApiIssue(apiIssue) : {
\t\tid: String(issueId),
\t\ttitle: '',
\t\tsummary: '',
\t\tcategory: 'Voice',
\t\ttopic: 'India',
\t\tcreator: 'Gist',
\t\tcreatedAt: '',
\t\tsupportCount: 0,
\t\topposeCount: 0,
\t\tquestionCount: 0,
\t\ttotalEngagement: 0,
\t\ttakes: [],
\t};

\tconst [counts, setCounts] = useState({ support: 0, oppose: 0, question: 0 });
\tconst [takes, setTakes] = useState<VoiceTake[]>([]);
\tconst [selectedStance, setSelectedStance] = useState<Stance | null>(null);
\tconst [quickTakeStance, setQuickTakeStance] = useState<Stance | null>(null);
\tconst [quickTakeText, setQuickTakeText] = useState('');
\tconst quickCommentInputRef = useRef<TextInput>(null);
\tconst [replyingToId, setReplyingToId] = useState<string | null>(null);
\tconst [replyDraftById, setReplyDraftById] = useState<Record<string, string>>({});
\tconst [replyIntentById, setReplyIntentById] = useState<Record<string, ReplyIntent>>({});
\tconst [saved, setSaved] = useState(false);
\tconst [following, setFollowing] = useState(true);

\t// Sync counts + stance from API issue
\tuseEffect(() => {
\t\tif (apiIssue) {
\t\t\tsetCounts({
\t\t\t\tsupport: apiIssue.support_count,
\t\t\t\toppose: apiIssue.oppose_count,
\t\t\t\tquestion: apiIssue.question_count,
\t\t\t});
\t\t\tsetSelectedStance(apiIssue.viewer_stance ?? null);
\t\t}
\t}, [apiIssue?.id]);

\t// Sync takes from API
\tuseEffect(() => {
\t\tif (apiTakes) {
\t\t\tsetTakes(apiTakes.map(mapApiTake));
\t\t}
\t}, [apiTakes]);

"""

# ─── Block 4: New onQuickStance (replaces lines 300–323, 0-indexed 299–322) ───
NEW_ON_QUICK_STANCE = """\
\tconst filteredTakes = useMemo(() => {
\t\tif (activeFilter === 'all') return takes;
\t\treturn takes.filter((item) => item.stance === activeFilter);
\t}, [activeFilter, takes]);

\tconst topAnswers = useMemo(() => {
\t\treturn [...takes].sort((a, b) => b.reactions - a.reactions).slice(0, 3);
\t}, [takes]);

\tconst goTo = (path: string) => router.push(path as never);
\tconst isActive = (path: string) => {
\t\tif (path === '/voice') {
\t\t\treturn pathname.startsWith('/voice') || pathname.startsWith('/voice-detail');
\t\t}
\t\treturn pathname === path;
\t};

\tconst onQuickStance = (stance: Stance) => {
\t\tif (selectedStance !== stance) {
\t\t\tsetCounts((prev) => {
\t\t\t\tconst next = { ...prev };
\t\t\t\tif (selectedStance) {
\t\t\t\t\tnext[selectedStance] = Math.max(0, next[selectedStance] - 1);
\t\t\t\t}
\t\t\t\tnext[stance] += 1;
\t\t\t\treturn next;
\t\t\t});
\t\t\tsetSelectedStance(stance);
\t\t\tstanceMutation.mutate({ issueId, stance });
\t\t}

\t\tif (stance === 'question') {
\t\t\tsetQuickTakeStance('question');
\t\t\tsetTimeout(() => {
\t\t\t\tquickCommentInputRef.current?.focus();
\t\t\t}, 0);
\t\t\treturn;
\t\t}

\t\tsetQuickTakeStance(null);
\t};

"""

# ─── Block 5: New appendTake (replaces lines 324–341, 0-indexed 323–340) ──────
NEW_APPEND_TAKE = """\
\tconst appendTake = (text: string, stance: Stance | null) => {
\t\tconst trimmed = text.trim();
\t\tif (!trimmed) return false;

\t\tconst newTake: VoiceTake = {
\t\t\tid: `take-local-${Date.now()}`,
\t\t\tauthor: 'You',
\t\t\tstance: stance ?? undefined,
\t\t\tcontent: trimmed,
\t\t\tcreatedAt: 'now',
\t\t\treactions: 0,
\t\t\treplies: [],
\t\t};

\t\tsetTakes((prev) => [newTake, ...prev]);
\t\tcreateTakeMutation.mutate({ body: trimmed, stance: stance ?? undefined });
\t\treturn true;
\t};

"""

# ─── Block 6: New onSubmitReply (replaces lines 371–416, 0-indexed 370–415) ───
NEW_ON_SUBMIT_REPLY = """\
\tconst onSubmitReply = (targetId: string) => {
\t\tconst draft = (replyDraftById[targetId] ?? '').trim();
\t\tif (!draft) return;
\t\tconst replyIntent = replyIntentById[targetId] ?? 'reply';

\t\tconst newReply: VoiceReply = {
\t\t\tid: `reply-${Date.now()}`,
\t\t\tauthor: 'You',
\t\t\tcontent: draft,
\t\t\tcreatedAt: 'now',
\t\t\tintent: replyIntent,
\t\t\treplies: [],
\t\t};

\t\tsetTakes((prev) => {
\t\t\tconst insertReply = (items: any[]): any[] | null => {
\t\t\t\tfor (let i = 0; i < items.length; i++) {
\t\t\t\t\tif (items[i].id === targetId) {
\t\t\t\t\t\tconst updated = [...items];
\t\t\t\t\t\tupdated[i] = {
\t\t\t\t\t\t\t...updated[i],
\t\t\t\t\t\t\treplies: [...(updated[i].replies || []), newReply],
\t\t\t\t\t\t};
\t\t\t\t\t\treturn updated;
\t\t\t\t\t}
\t\t\t\t\tif (items[i].replies && items[i].replies.length > 0) {
\t\t\t\t\t\tconst nextLevel = insertReply(items[i].replies);
\t\t\t\t\t\tif (nextLevel) {
\t\t\t\t\t\t\tconst updated = [...items];
\t\t\t\t\t\t\tupdated[i] = { ...updated[i], replies: nextLevel };
\t\t\t\t\t\t\treturn updated;
\t\t\t\t\t\t}
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\treturn null;
\t\t\t};
\t\t\treturn insertReply(prev) || prev;
\t\t});

\t\t// Call API for persisted (non-optimistic) parent takes
\t\tconst numericParentId = Number(targetId);
\t\tif (!targetId.startsWith('take-local') && !isNaN(numericParentId)) {
\t\t\tconst replyStance = replyIntent !== 'reply' ? replyIntent as Stance : undefined;
\t\t\tcreateTakeMutation.mutate({ body: draft, stance: replyStance, parentTakeId: numericParentId });
\t\t}

\t\tsetReplyDraftById((prev) => ({ ...prev, [targetId]: '' }));
\t\tsetReplyingToId(null);
\t};

"""

# Build the new content
new_content = (
    NEW_IMPORTS
    + ''.join(lines[15:105])   # type defs: lines 16–105 (0-indexed 15–104)
    + MAPPERS
    + NEW_SCREEN_SETUP
    + NEW_ON_QUICK_STANCE
    + NEW_APPEND_TAKE
    + ''.join(lines[341:370])  # onPostQuickTake + onOpenReplyComposer (lines 342–370)
    + NEW_ON_SUBMIT_REPLY
    + ''.join(lines[415:1042]) # onShare + content JSX + component functions (lines 416–1042)
    + ''.join(lines[1123:])    # compactCount + styles (lines 1124+)
)

with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
    f.write(new_content)

print('Done. Total lines written:', len(new_content.splitlines()))
print('Sample line 106:', repr(new_content.splitlines()[105][:60]))
