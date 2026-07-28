<?php
// insert.php
// Receives CO2 + PM2.5 + PM10 + Temperature + Humidity from ESP32
// Expected: insert.php?co2=500&pm25=10&pm10=15&temperature=28.5&humidity=65.2

date_default_timezone_set('Asia/Kuala_Lumpur');

$host   = "sakura.proxy.rlwy.net";
$port   = 51259;
$dbname = "railway";
$user   = "root";
$pass   = "wAlJGPvJVZjhzuSNeHSWipPXsGBLNAbk";

header("Content-Type: application/json");

$conn = new mysqli($host, $user, $pass, $dbname, $port);

if ($conn->connect_error) {
    http_response_code(500);
    echo json_encode(["status" => "error", "message" => "DB connection failed: " . $conn->connect_error]);
    exit;
}

$co2         = isset($_REQUEST['co2'])         ? floatval($_REQUEST['co2'])         : null;
$pm25        = isset($_REQUEST['pm25'])        ? floatval($_REQUEST['pm25'])        : null;
$pm10        = isset($_REQUEST['pm10'])        ? floatval($_REQUEST['pm10'])        : null;
$temperature = isset($_REQUEST['temperature']) ? floatval($_REQUEST['temperature']) : null;
$humidity    = isset($_REQUEST['humidity'])    ? floatval($_REQUEST['humidity'])    : null;

if ($co2 === null) {
    http_response_code(400);
    echo json_encode(["status" => "error", "message" => "Missing co2 parameter"]);
    $conn->close();
    exit;
}

$now = date('Y-m-d H:i:s');

$stmt = $conn->prepare("INSERT INTO air_quality_v2 (co2, pm25, pm10, temperature, humidity, timestamp) VALUES (?, ?, ?, ?, ?, ?)");
$stmt->bind_param("ddddds", $co2, $pm25, $pm10, $temperature, $humidity, $now);

if ($stmt->execute()) {
    echo json_encode([
        "status"      => "success",
        "co2"         => $co2,
        "pm25"        => $pm25,
        "pm10"        => $pm10,
        "temperature" => $temperature,
        "humidity"    => $humidity,
        "timestamp"   => $now,
        "id"          => $conn->insert_id
    ]);
} else {
    http_response_code(500);
    echo json_encode(["status" => "error", "message" => "Insert failed: " . $stmt->error]);
}

$stmt->close();
$conn->close();
?>
