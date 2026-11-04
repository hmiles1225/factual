<?php
// Texas election-night results (Heston, 2026-10-30): the Texas Secretary of State's own unofficial count, read
// from its results feed (the data behind goelect.txelections.civixapps.com/ivis-enr-ui), as published; no AI.
// The count and the share counted, never a call or a projection. The scan runs too rarely for election night, so
// this server reads the feed itself: at most once a minute however many readers there are, under our own name,
// and readers' browsers contact only our domain. Returns {"live": false} until LIVE is switched on.
declare(strict_types=1);
ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');

// Off until Heston decides (2026-10-30): the state's results website puts a robot check (Cloudflare Turnstile)
// in front of browsers; the feed behind it asks for none, and robots.txt allows every agent. His rule is that we
// never get past a robot check, so whether reading the feed is fair use is his call.
const LIVE = true;   // Heston 2026-10-30: "Yes keep the election results going"
const ELECTION_ID = '53815';  // 2026 NOVEMBER GENERAL ELECTION
const FEED = 'https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/' . ELECTION_ID;
const SITE = 'https://goelect.txelections.civixapps.com/ivis-enr-ui/races';
const UA = 'fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)';
const EVERY = 60;  // seconds between reads of the feed
const COUNTY_INFO = 'https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/countyInfo/' . ELECTION_ID;
const CLARITY = 'https://results.enr.clarityelections.com/';
// The biggest counties' own results sites (Heston, 2026-11-03: "the numbers arent matching what im seeing on tv"). The
// state posts the counties' uploads in batches, well behind the counties themselves, which is what TV shows. For each
// county below, in each race, when the county's own count is ahead of what the state has from that county, the
// county's count replaces the state's for that county. Never added on top, so nothing is counted twice. Only sites
// that let us read without a robot check: Dallas County's (an AWS challenge) is not one of them.
const COUNTIES = [
    'TARRANT' => ['clarity', 'TX/Tarrant/127297'],
    'TRAVIS'  => ['clarity', 'TX/Travis/127492'],
    'HARRIS'  => ['harris', 'https://appfiles.harrisvotes.com/harrisvotes/prd/Data/1126/resultsbyballot.json',
                  'https://www.harrisvotes.com/Election-Results/Live-Results'],
];

if (!LIVE) { echo json_encode(['live' => false]); exit; }
set_time_limit(90);

$dir = __DIR__ . '/store';
if (!is_dir($dir)) mkdir($dir, 0700, true);
$cache = $dir . '/results.json';
$age = is_file($cache) ? time() - filemtime($cache) : PHP_INT_MAX;

if ($age >= EVERY) {
    // One reader refreshes; everyone else gets the copy on hand. A failed read keeps the last good copy.
    $lock = fopen($dir . '/results.lock', 'c');
    if ($lock && flock($lock, LOCK_EX | LOCK_NB)) {
        clearstatcache();
        if (!is_file($cache) || time() - filemtime($cache) >= EVERY) {
            $out = read_feed();
            if ($out) file_put_contents($cache . '.tmp', json_encode($out)) && rename($cache . '.tmp', $cache);
            else @touch($cache);  // wait a minute before trying again, not one try per reader
        }
        flock($lock, LOCK_UN);
    }
}

$body = is_file($cache) ? (string) file_get_contents($cache) : '';
if ($body === '' || $body === 'null') { echo json_encode(['live' => true, 'counted' => false, 'error' => 'not read yet']); exit; }
$res = json_decode($body, true);
$res['checked_at'] = gmdate('c', (int) filemtime($cache));
echo json_encode($res);

function get(string $url): ?string { return get_all([$url])[0]; }

// Several reads at once, so a slow county never holds up the rest: one answer (or null) per URL, in order.
function get_all(array $urls): array {
    $mh = curl_multi_init(); $hs = [];
    foreach ($urls as $i => $url) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20, CURLOPT_CONNECTTIMEOUT => 8,
            CURLOPT_USERAGENT => UA, CURLOPT_HTTPHEADER => ['Accept: application/json'], CURLOPT_ENCODING => '']);
        curl_multi_add_handle($mh, $ch); $hs[$i] = $ch;
    }
    do { $st = curl_multi_exec($mh, $run); if ($run) curl_multi_select($mh, 1.0); } while ($run && $st === CURLM_OK);
    $out = [];
    foreach ($hs as $i => $ch) {
        $b = curl_multi_getcontent($ch);
        $GLOBALS['codes'][parse_url($urls[$i], PHP_URL_HOST)] = curl_getinfo($ch, CURLINFO_HTTP_CODE) . (curl_error($ch) ? ' ' . curl_error($ch) : '');
        $out[$i] = (curl_getinfo($ch, CURLINFO_HTTP_CODE) === 200 && is_string($b) && $b !== '') ? $b : null;
        curl_multi_remove_handle($mh, $ch);
    }
    curl_multi_close($mh);
    return $out;
}

// Office names differ only in punctuation and case between the state and the counties ("U. S. SENATOR",
// "United States Senator"; "Place 2 - Unexpired Term", "Place 2, (Unexpired Term)").
function office_key(string $n): string {
    $n = strtolower($n);
    $n = preg_replace('/\bu\.?\s*s\.?\s+/', 'united states ', $n);
    return preg_replace('/[^a-z0-9]/', '', $n);
}

// One county's own count: office key => [[candidate name, votes], ...], and the county's own time.
function read_county(string $name, array $src): ?array {
    $races = []; $updated = ''; $link = '';
    if ($src[0] === 'clarity') {
        $base = CLARITY . $src[1] . '/';
        $link = $base;
        [$ver] = get_all([$base . 'current_ver.txt']);
        $ver = trim((string) $ver);
        if (!preg_match('/^\d+$/', $ver)) return null;
        [$sum, $set] = get_all([$base . $ver . '/json/en/summary.json', $base . $ver . '/json/en/electionsettings.json']);
        $rows = $sum ? json_decode($sum, true) : null;
        if (!is_array($rows)) return null;
        $settings = $set ? json_decode($set, true) : null;
        $updated = (string) ($settings['websiteupdatedat'] ?? '');
        foreach ($rows as $r) {
            if (!isset($r['C'], $r['CH'], $r['V'])) continue;
            $races[office_key((string) $r['C'])] = array_map(null, $r['CH'], array_map('intval', $r['V']));
        }
    } elseif ($src[0] === 'harris') {
        $link = $src[2];
        // The county's own page asks for a new copy each minute this way; a fixed key would get a cached copy.
        $raw = get($src[1] . '?nocache=' . (intdiv(time(), 60) * 60000));
        $d = $raw ? json_decode($raw, true) : null;
        if (!is_array($d) || !isset($d['contests'])) return null;
        $updated = (string) ($d['dt'] ?? '');
        foreach ($d['contests'] as $c) {
            if (!isset($c['t'], $c['ca'], $c['tv'])) continue;
            $races[office_key((string) $c['t'])] = array_map(null, $c['ca'], array_map('intval', $c['tv']));
        }
    }
    return $races ? ['county' => $name, 'updated' => $updated, 'source' => $link, 'races' => $races] : null;
}

// The county's count for one race, candidate by candidate in the state's order, or null when any named candidate
// cannot be matched to exactly one of the county's (then the state's numbers stand for that county).
function county_votes(array $stateCands, array $countyRows): ?array {
    $out = [];
    foreach ($stateCands as $i => $c) {
        if ($c['party'] === 'W') continue;  // write-ins: the state's numbers stand
        $last = strtoupper($c['last']);
        if ($last === '') return null;
        $hits = array_values(array_filter($countyRows, fn($x) => preg_match('/\b' . preg_quote($last, '/') . '\b/', strtoupper((string) $x[0]))));
        if (count($hits) > 1 && $c['first'] !== '') {  // two candidates share a last name (Kyle and Kristen Hawkins)
            $first = strtoupper($c['first']);
            $hits = array_values(array_filter($hits, fn($x) => preg_match('/\\b' . preg_quote($first, '/') . '\\b/', strtoupper((string) $x[0]))));
        }
        if (count($hits) !== 1) return null;
        $out[$i] = $hits[0][1];
    }
    return $out;
}

// The feed: JSON whose parts are base64 JSON. Kept: when it was updated, how much has reported, and every
// candidate's votes in the U.S. Senate race and the statewide races. Nothing is computed here but sums.
function read_feed(): ?array {
    $raw = get(FEED);
    $f = $raw ? json_decode($raw, true) : null;
    if (!is_array($f) || !isset($f['Home'], $f['StateWide'], $f['Federal'])) return null;
    $part = fn($k) => json_decode((string) base64_decode((string) ($f[$k] ?? '')), true) ?: [];
    $home = $part('Home');
    $races = [];
    $senate = array_values(array_filter($part('Federal')['Races'] ?? [], fn($r) => trim($r['N']) === 'U. S. SENATOR'));
    foreach (array_merge($senate, $part('StateWide')['Races'] ?? []) as $r) {
        $cands = [];
        foreach ($r['Candidates'] ?? [] as $c) {
            $cands[] = ['name' => (string) $c['N'], 'first' => (string) ($c['FN'] ?? ''), 'last' => (string) ($c['LN'] ?? ''),
                'party' => (string) ($c['P'] ?? ''), 'votes' => (int) ($c['V'] ?? 0), 'early' => (int) ($c['EV'] ?? 0),
                'ballot' => (int) ($c['O'] ?? 0)];
        }
        $races[] = ['office' => trim((string) $r['N']), 'total' => (int) ($r['T'] ?? 0), 'candidates' => $cands];
    }
    if (!$races) return null;
    $direct = merge_counties($races);
    $counted = array_sum(array_column($races, 'total')) > 0;
    return ['live' => true, 'counted' => $counted, 'election' => ELECTION_ID, 'source' => SITE,
        'updated' => (string) ($home['LastUpdatedTime'] ?? ''),  // the Secretary of State's own time, in UTC
        'counties' => [(int) ($home['CountiesReporting']['CR'] ?? 0), (int) ($home['CountiesReporting']['CT'] ?? 0)],
        'polling_places' => [(int) ($home['PollingReporting']['PLR'] ?? 0), (int) ($home['PollingReporting']['PLT'] ?? 0)],
        'direct' => $direct, 'direct_notes' => $GLOBALS['why'] ?? [], 'reads' => $GLOBALS['codes'] ?? [], 'races' => $races];
}

// Swap in each county's own count where it is ahead of the state's for that county. Returns the counties used.
function merge_counties(array &$races): array {
    $dir = __DIR__ . '/store';
    $info = get(COUNTY_INFO);
    $byCounty = [];
    $ci = $info ? json_decode((string) base64_decode((string) (json_decode($info, true)['upload'] ?? '')), true) : null;
    $GLOBALS['why'] = [];  // what happened with each county, in the response, so a failed read is visible
    if (!is_array($ci)) { $GLOBALS['why'][] = 'state county rows: ' . ($info ? 'unreadable' : 'not read'); return []; }
    foreach ($ci as $c) $byCounty[(string) ($c['N'] ?? '')] = $c;
    $used = [];
    foreach (COUNTIES as $name => $src) {
        $cache = "$dir/county-" . strtolower($name) . '.json';
        $county = read_county($name, $src);
        if ($county) file_put_contents($cache, json_encode($county));
        elseif (is_file($cache)) $county = json_decode((string) file_get_contents($cache), true);  // last good copy
        if (!$county || !isset($byCounty[$name])) { $GLOBALS['why'][] = "$name: " . (!$county ? 'not read' : 'not in state rows'); continue; }
        $stateRaces = [];
        foreach ($byCounty[$name]['Races'] ?? [] as $r) $stateRaces[office_key((string) $r['N'])] = $r;
        $senate = 0;
        foreach ($races as &$race) {
            $k = office_key($race['office']);
            $rows = $county['races'][$k] ?? null;
            if (!$rows) continue;
            $cv = county_votes($race['candidates'], $rows);
            if ($cv === null) continue;
            $sr = $stateRaces[$k] ?? ['C' => [], 'T' => 0];
            $stateBy = [];
            foreach ($sr['C'] ?? [] as $x) $stateBy[strtoupper((string) ($x['LN'] ?? ''))] = (int) ($x['V'] ?? 0);
            $stateNamed = 0;
            foreach ($cv as $i => $v) $stateNamed += $stateBy[strtoupper($race['candidates'][$i]['last'])] ?? 0;
            if (array_sum($cv) <= $stateNamed) continue;  // the state has caught up with this county
            foreach ($cv as $i => $v) {
                $c = &$race['candidates'][$i];
                $c['votes'] += $v - ($stateBy[strtoupper($c['last'])] ?? 0);
                unset($c);
            }
            $race['total'] = array_sum(array_column($race['candidates'], 'votes'));
            $race['direct'][] = $name;
            $race['early_partial'] = true;  // the counties' own sites do not all split out early votes
            if ($k === office_key('U. S. SENATOR')) $senate = array_sum($cv);
        }
        unset($race);
        $GLOBALS['why'][] = "$name: " . ($senate ? 'used' : 'state is level or ahead');
        if ($senate) $used[] = ['county' => $name, 'updated' => $county['updated'], 'source' => $county['source'], 'senate_votes' => $senate];
    }
    return $used;
}
