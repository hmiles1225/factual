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
const LIVE = false;
const ELECTION_ID = '53815';  // 2026 NOVEMBER GENERAL ELECTION
const FEED = 'https://goelect.txelections.civixapps.com/api-ivis-system/api/s3/enr/election/' . ELECTION_ID;
const SITE = 'https://goelect.txelections.civixapps.com/ivis-enr-ui/races';
const UA = 'fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)';
const EVERY = 60;  // seconds between reads of the feed

if (!LIVE) { echo json_encode(['live' => false]); exit; }

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

function get(string $url): ?string {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 25, CURLOPT_USERAGENT => UA,
        CURLOPT_HTTPHEADER => ['Accept: application/json'], CURLOPT_ENCODING => '']);
    $b = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    return ($b !== false && $code === 200) ? $b : null;
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
    $counted = array_sum(array_column($races, 'total')) > 0;
    return ['live' => true, 'counted' => $counted, 'election' => ELECTION_ID, 'source' => SITE,
        'updated' => (string) ($home['LastUpdatedTime'] ?? ''),  // the Secretary of State's own time, Central
        'counties' => [(int) ($home['CountiesReporting']['CR'] ?? 0), (int) ($home['CountiesReporting']['CT'] ?? 0)],
        'polling_places' => [(int) ($home['PollingReporting']['PLR'] ?? 0), (int) ($home['PollingReporting']['PLT'] ?? 0)],
        'races' => $races];
}
