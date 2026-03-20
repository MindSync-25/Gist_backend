import sys

filepath = r"C:\Users\rajan\OneDrive\Desktop\GIST\Gist_frontend\app\(tabs)\voice.tsx"
with open(filepath, encoding="utf-8") as f:
    lines = f.readlines()

print("Total lines:", len(lines))
print("Line 68:", repr(lines[67][:70]))
print("Line 69:", repr(lines[68][:70]))
print("Line 149:", repr(lines[148][:70]))
print("Line 150:", repr(lines[149][:70]))
print("Line 315:", repr(lines[314][:70]))
print("Line 316:", repr(lines[315][:70]))

MAPPERS = """\
// --- Mappers: API types -> local component types ---

function mapIssue(issue: ApiVoiceIssue): IssueCard {
\treturn {
\t\tid: String(issue.id),
\t\ttitle: issue.title,
\t\tcontext: issue.context,
\t\ttags: issue.tags as VoiceFilter[],
\t\tsupport: issue.support_count,
\t\toppose: issue.oppose_count,
\t\tquestion: issue.question_count,
\t\treactingNow: issue.reacting_now,
\t};
}

function mapPoll(poll: ApiVoicePoll) {
\treturn {
\t\tid: String(poll.id),
\t\tlabel: poll.label,
\t\tquestion: poll.question,
\t\toptions: poll.options.map((o) => ({
\t\t\tid: String(o.id),
\t\t\tlabel: o.label,
\t\t\tpercentage: o.percentage,
\t\t\tvotes: o.votes,
\t\t})) satisfies PollOption[],
\t\ttotalVotes: poll.total_votes,
\t\ttimeInfo: poll.time_info,
\t};
}

function mapTopVoice(v: ApiTopVoice, index: number): TopVoice {
\tconst labels: TopVoice['label'][] = ['Top Voice', 'Sharpest Take', 'Balanced View', 'Rising Voice'];
\treturn {
\t\tid: String(v.id),
\t\tname: v.name,
\t\tlabel: labels[index] ?? 'Top Voice',
\t};
}

"""

VOICE_SCREEN = """\
export default function VoiceScreen() {
\tconst router = useRouter();
\tconst pathname = usePathname();
\tconst paddingTop = Platform.OS === 'web' ? 0 : 6;

\tconst [activeFilter, setActiveFilter] = useState<VoiceFilter>('Trending');
\tconst [query, setQuery] = useState('');
\tconst [selectedPollOption, setSelectedPollOption] = useState<string | null>(null);
\tconst [featuredPosition, setFeaturedPosition] = useState<QuickPosition | null>(null);
\tconst [issuePositions, setIssuePositions] = useState<Record<string, QuickPosition | null>>({});

\t// API data
\tconst { data: featuredData } = useFeaturedIssue();
\tconst { data: issuesData } = useVoiceIssues(activeFilter, query);
\tconst { data: pollData } = useActivePoll();
\tconst { data: topVoicesData } = useTopVoices();
\tconst { data: streamData } = useParticipationStream();
\tconst stanceMutation = useSetStance();
\tconst pollVoteMutation = useVotePoll();

\t// Map API data to component types
\tconst featuredIssue = featuredData ? mapIssue(featuredData) : null;
\tconst activeIssues = issuesData?.map(mapIssue) ?? [];
\tconst livePoll = pollData ? mapPoll(pollData) : null;
\tconst topVoices = topVoicesData?.map((v, i) => mapTopVoice(v, i)) ?? [];
\tconst participationStream = streamData?.map((s) => s.text) ?? [];

\t// Derive displayed stance (optimistic local override takes precedence over API value)
\tconst featuredDisplayPos: QuickPosition | null = featuredPosition ?? (featuredData?.viewer_stance ?? null);

\tconst { width } = useWindowDimensions();
\tconst isDesktopWeb = Platform.OS === 'web' && width >= 1024;

\tconst goTo = (path: string) => router.push(path as never);
\tconst isActive = (path: string) => pathname === path;

\tconst openVoiceDetail = (issue: IssueCard) => {
\t\trouter.push({
\t\t\tpathname: '/voice-detail/[id]',
\t\t\tparams: { id: issue.id },
\t\t} as never);
\t};

\tconst handleFeaturedPosition = (position: QuickPosition) => {
\t\tsetFeaturedPosition(position);
\t\tif (featuredData) {
\t\t\tstanceMutation.mutate({ issueId: featuredData.id, stance: position });
\t\t}
\t};

\tconst handleIssuePosition = (issue: IssueCard, position: QuickPosition, apiId: number) => {
\t\tsetIssuePositions((prev) => ({ ...prev, [issue.id]: position }));
\t\tif (apiId > 0) stanceMutation.mutate({ issueId: apiId, stance: position });
\t};

\tconst handlePollVote = (optionId: string) => {
\t\tsetSelectedPollOption(optionId);
\t\tif (pollData) {
\t\t\tpollVoteMutation.mutate({ pollId: pollData.id, optionId: Number(optionId) });
\t\t}
\t};

\tconst displayedPollOption = selectedPollOption ??
\t\t(pollData?.viewer_voted_option_id ? String(pollData.viewer_voted_option_id) : null);

\tconst voiceContent = (
\t\t<ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={[styles.scrollContent, { paddingTop }]}>
\t\t\t<VoiceHeader query={query} onChangeQuery={setQuery} hideTitle={isDesktopWeb} />
\t\t\t<FilterChipRow activeFilter={activeFilter} onChange={setActiveFilter} />

\t\t\t{featuredIssue && (
\t\t\t\t<FeaturedIssueCard
\t\t\t\t\tissue={featuredIssue}
\t\t\t\t\tselectedPosition={featuredDisplayPos}
\t\t\t\t\tonSelectPosition={handleFeaturedPosition}
\t\t\t\t\tonOpenDiscussion={() => openVoiceDetail(featuredIssue)}
\t\t\t\t/>
\t\t\t)}

\t\t\t{livePoll && (
\t\t\t\t<LivePollCard
\t\t\t\t\tpoll={livePoll}
\t\t\t\t\tselectedOption={displayedPollOption}
\t\t\t\t\tonSelectOption={handlePollVote}
\t\t\t\t/>
\t\t\t)}

\t\t\t<View style={styles.sectionRow}>
\t\t\t\t<Text style={styles.sectionTitle}>Trending now</Text>
\t\t\t\t<Text style={styles.sectionMeta}>Most discussed</Text>
\t\t\t</View>

\t\t\t<View style={styles.issueList}>
\t\t\t\t{activeIssues.map((issue, idx) => {
\t\t\t\t\tconst apiIssue = issuesData?.[idx];
\t\t\t\t\tconst displayPos = (issuePositions[issue.id] ?? (apiIssue?.viewer_stance ?? null)) as QuickPosition | null;
\t\t\t\t\treturn (
\t\t\t\t\t\t<IssueActionCard
\t\t\t\t\t\t\tkey={issue.id}
\t\t\t\t\t\t\tissue={issue}
\t\t\t\t\t\t\tselectedPosition={displayPos}
\t\t\t\t\t\t\tonSelectPosition={(position) => handleIssuePosition(issue, position, apiIssue?.id ?? 0)}
\t\t\t\t\t\t\tonOpenDiscussion={() => openVoiceDetail(issue)}
\t\t\t\t\t\t/>
\t\t\t\t\t);
\t\t\t\t})}
\t\t\t</View>

\t\t\t{topVoices.length > 0 && <TopVoicesRow voices={topVoices} />}
\t\t\t{featuredIssue && <TopTakeCard onOpenDiscussion={() => openVoiceDetail(featuredIssue)} />}

\t\t\t{participationStream.length > 0 && (
\t\t\t\t<View style={styles.streamCard}>
\t\t\t\t\t<Text style={styles.streamLabel}>Issue participation</Text>
\t\t\t\t\t{participationStream.map((item) => (
\t\t\t\t\t\t<View key={item} style={styles.streamItemRow}>
\t\t\t\t\t\t\t<View style={styles.streamDot} />
\t\t\t\t\t\t\t<Text style={styles.streamItem}>{item}</Text>
\t\t\t\t\t\t</View>
\t\t\t\t\t))}
\t\t\t\t\t{featuredIssue && (
\t\t\t\t\t\t<Pressable style={styles.streamButton} onPress={() => openVoiceDetail(featuredIssue)}>
\t\t\t\t\t\t\t<Text style={styles.streamButtonText}>Open issue threads</Text>
\t\t\t\t\t\t</Pressable>
\t\t\t\t\t)}
\t\t\t\t</View>
\t\t\t)}
\t\t</ScrollView>
\t);

\tif (isDesktopWeb) {
\t\treturn (
\t\t\t<Screen>
\t\t\t\t<View style={styles.webShell}>
\t\t\t\t\t<View style={styles.webLeftRail}>
\t\t\t\t\t\t<Text style={styles.webBrandWordmark}>Gist</Text>
\t\t\t\t\t\t<WebNavItem icon="home" label="Home" active={isActive('/')} onPress={() => goTo('/')} />
\t\t\t\t\t\t<WebNavItem icon="search" label="Explore" active={isActive('/explore')} onPress={() => goTo('/explore')} />
\t\t\t\t\t\t<WebNavItem icon="add-circle-outline" label="Create" active={isActive('/create')} onPress={() => goTo('/create')} />
\t\t\t\t\t\t<WebNavItem icon="film-outline" label="Series" active={isActive('/series')} onPress={() => goTo('/series')} />
\t\t\t\t\t\t<WebNavItem icon="megaphone-outline" label="Voice" active={isActive('/voice')} onPress={() => goTo('/voice')} />
\t\t\t\t\t\t<WebNavItem icon="chatbubble-outline" label="Messages" active={isActive('/messages')} onPress={() => goTo('/messages')} />
\t\t\t\t\t\t<WebNavItem icon="notifications-outline" label="Notifications" active={isActive('/notifications')} onPress={() => goTo('/notifications')} />
\t\t\t\t\t\t<WebNavItem icon="person-outline" label="Profile" active={isActive('/profile')} onPress={() => goTo('/profile')} />
\t\t\t\t\t\t<WebNavItem icon="settings-outline" label="Settings" active={isActive('/settings')} onPress={() => goTo('/settings')} />
\t\t\t\t\t</View>

\t\t\t\t\t<View style={styles.webCenterColumn}>
\t\t\t\t\t\t<View style={styles.desktopVoiceHeader}>
\t\t\t\t\t\t\t<Text style={styles.desktopVoiceTitle}>Voice</Text>
\t\t\t\t\t\t\t<View style={styles.webTopProfilePic} />
\t\t\t\t\t\t</View>
\t\t\t\t\t\t{voiceContent}
\t\t\t\t\t</View>

\t\t\t\t\t<View style={styles.webRightRail}>
\t\t\t\t\t\t<ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.webRightSidebarScroll}>
\t\t\t\t\t\t\t<Text style={styles.widgetHeader}>Top Voices</Text>
\t\t\t\t\t\t\t{topVoices.map((v) => (
\t\t\t\t\t\t\t\t<View key={v.id} style={styles.widgetVoiceRow}>
\t\t\t\t\t\t\t\t\t<View style={styles.widgetVoiceAvatar} />
\t\t\t\t\t\t\t\t\t<View style={{ flex: 1 }}>
\t\t\t\t\t\t\t\t\t\t<Text style={styles.widgetVoiceName}>{v.name}</Text>
\t\t\t\t\t\t\t\t\t\t<Text style={styles.widgetVoiceLabel}>{v.label}</Text>
\t\t\t\t\t\t\t\t\t</View>
\t\t\t\t\t\t\t\t</View>
\t\t\t\t\t\t\t))}

\t\t\t\t\t\t\t<Text style={[styles.widgetHeader, { marginTop: 28 }]}>Trending Issues</Text>
\t\t\t\t\t\t\t{activeIssues.slice(0, 3).map((issue) => (
\t\t\t\t\t\t\t\t<Pressable key={issue.id} style={styles.widgetIssueRow} onPress={() => openVoiceDetail(issue)}>
\t\t\t\t\t\t\t\t\t<Text style={styles.widgetIssueTitle} numberOfLines={2}>{issue.title}</Text>
\t\t\t\t\t\t\t\t\t<Text style={styles.widgetIssueMeta}>{issue.reactingNow.toLocaleString()} reacting</Text>
\t\t\t\t\t\t\t\t</Pressable>
\t\t\t\t\t\t\t))}

\t\t\t\t\t\t\t<Text style={[styles.widgetHeader, { marginTop: 28 }]}>Live Activity</Text>
\t\t\t\t\t\t\t{participationStream.map((item, i) => (
\t\t\t\t\t\t\t\t<View key={i} style={styles.widgetActivityRow}>
\t\t\t\t\t\t\t\t\t<View style={styles.widgetActivityDot} />
\t\t\t\t\t\t\t\t\t<Text style={styles.widgetActivityText}>{item}</Text>
\t\t\t\t\t\t\t\t</View>
\t\t\t\t\t\t\t))}
\t\t\t\t\t\t</ScrollView>
\t\t\t\t\t</View>
\t\t\t\t</View>
\t\t\t</Screen>
\t\t);
\t}

\treturn <Screen>{voiceContent}</Screen>;
}

"""

# keep lines 0-67 (types + FILTERS array, 1-indexed lines 1-68)
# replace lines 68-147 (0-indexed, hardcoded constants) with MAPPERS
# replace lines 148-313 (0-indexed, VoiceScreen function) with VOICE_SCREEN
# keep lines 314+ (sub-components + styles)

new_content = (
    ''.join(lines[:68])
    + MAPPERS
    + VOICE_SCREEN
    + ''.join(lines[315:])
)

with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
    f.write(new_content)

print('Done. Total lines written:', len(new_content.splitlines()))
