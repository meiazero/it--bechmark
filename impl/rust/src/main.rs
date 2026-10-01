#![forbid(unsafe_code)]
mod dsp;

use dsp::{Config, Counts, Worker, batch_seed, noise_variance, splitmix};
use rayon::prelude::*;
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Value, json};
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, mpsc};
use std::time::Instant;

const BATCH_BITS: u64 = dsp::BITS_PER_BATCH;
thread_local! { static WORKER: RefCell<Option<Worker>> = const { RefCell::new(None) }; }

// serde handles JSON syntax; this visitor adds the contract's duplicate-key
// rejection while retaining exact integer seeds and counters.
struct Strict(Value);
impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct StrictVisitor;
        impl<'de> Visitor<'de> for StrictVisitor {
            type Value = Strict;
            fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
                f.write_str("finite JSON with unique keys")
            }
            fn visit_bool<E: de::Error>(self, v: bool) -> Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_i64<E: de::Error>(self, v: i64) -> Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_u64<E: de::Error>(self, v: u64) -> Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_f64<E: de::Error>(self, v: f64) -> Result<Strict, E> {
                serde_json::Number::from_f64(v)
                    .map(|x| Strict(Value::Number(x)))
                    .ok_or_else(|| E::custom("Non-finite JSON number"))
            }
            fn visit_str<E: de::Error>(self, v: &str) -> Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_string<E: de::Error>(self, v: String) -> Result<Strict, E> {
                Ok(Strict(json!(v)))
            }
            fn visit_unit<E: de::Error>(self) -> Result<Strict, E> {
                Ok(Strict(Value::Null))
            }
            fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Strict, A::Error> {
                let mut values = Vec::new();
                while let Some(Strict(value)) = seq.next_element()? {
                    values.push(value);
                }
                Ok(Strict(Value::Array(values)))
            }
            fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Strict, A::Error> {
                let mut values = Map::new();
                while let Some((key, Strict(value))) = map.next_entry::<String, Strict>()? {
                    if values.insert(key, value).is_some() {
                        return Err(de::Error::custom("Duplicate JSON key"));
                    }
                }
                Ok(Strict(Value::Object(values)))
            }
        }
        deserializer.deserialize_any(StrictVisitor)
    }
}
fn parse(bytes: &[u8]) -> Result<Value, String> {
    serde_json::from_slice::<Strict>(bytes)
        .map(|x| x.0)
        .map_err(|e| e.to_string())
}
fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .to_path_buf()
}
fn object_keys(value: &Value, reference: &Value) -> Result<(), String> {
    let object = value.as_object().ok_or("Expected object")?;
    let expected = reference.as_object().unwrap();
    if object.keys().ne(expected.keys()) {
        return Err("Object keys differ".into());
    }
    Ok(())
}
fn integer(value: &Value, name: &str, min: u64, max: u64) -> Result<u64, String> {
    value
        .as_u64()
        .filter(|&x| x >= min && x <= max)
        .ok_or_else(|| format!("{name} must be a u64 in the permitted range"))
}
fn validate(value: &Value, mode: &str) -> Result<(), String> {
    let reference =
        parse(&fs::read(root().join("contract/profile_main.json")).map_err(|e| e.to_string())?)?;
    object_keys(value, &reference)?;
    for name in [
        "schema_version",
        "profile_id",
        "N_fft",
        "N_cp",
        "M",
        "active_bins",
        "pilot_bins",
        "data_bins",
        "pilots",
        "pdp",
        "E_sym",
        "bits_per_symbol",
        "B",
        "warmup_batches",
    ] {
        if value[name] != reference[name] {
            return Err(format!("{name} differs from frozen profile"));
        }
    }
    integer(&value["master_seed"], "master_seed", 0, u64::MAX)?;
    if value["channel"] != "rayleigh" && value["channel"] != "awgn" {
        return Err("Unknown channel".into());
    }
    if value["csi"] != "estimated" && value["csi"] != "perfect" {
        return Err("Unknown CSI".into());
    }
    let ber = &value["ber"];
    object_keys(ber, &reference["ber"])?;
    integer(&ber["target_errors"], "target_errors", 1, u64::MAX)?;
    let min = integer(&ber["min_batches"], "min_batches", 1, u64::MAX)?;
    let max = integer(&ber["max_bits"], "max_bits", 1, u64::MAX - BATCH_BITS + 1)?;
    if min > max / BATCH_BITS {
        return Err("max_bits below minimum batch payload".into());
    }
    let points = ber["ebn0_db"]
        .as_array()
        .filter(|x| !x.is_empty())
        .ok_or("Empty Eb/N0 points")?;
    for p in points {
        noise_variance(p.as_f64().ok_or("Expected finite Eb/N0 number")?)?;
    }
    object_keys(&value["perf"], &reference["perf"])?;
    if value["perf"]["ebn0_db"].as_u64() != Some(10) {
        return Err("perf Eb/N0 must be integer 10".into());
    }
    if value["perf"]["n_batches"].is_null() {
        if mode == "perf" {
            return Err("perf.n_batches awaits M8 calibration".into());
        }
    } else {
        integer(
            &value["perf"]["n_batches"],
            "perf.n_batches",
            1,
            u64::MAX / BATCH_BITS,
        )?;
    }
    object_keys(&value["stages"], &reference["stages"])?;
    integer(
        &value["stages"]["repetitions"],
        "stages.repetitions",
        1,
        u64::MAX,
    )?;
    if (mode == "perf" || mode == "stages") && value["csi"] != "estimated" {
        return Err("Perfect CSI is diagnostic only".into());
    }
    Ok(())
}
struct Arguments {
    config: Value,
    bytes: Vec<u8>,
    mode: String,
    workers: usize,
    output: PathBuf,
}
fn arguments() -> Result<Arguments, String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.len() != 8 {
        return Err("Usage: ofdm-rust --config FILE --mode MODE --workers P --out FILE".into());
    }
    let mut options = BTreeMap::new();
    for pair in args.as_chunks::<2>().0 {
        if !["--config", "--mode", "--workers", "--out"].contains(&pair[0].as_str())
            || options.insert(pair[0].clone(), pair[1].clone()).is_some()
        {
            return Err("Unknown or duplicate CLI option".into());
        }
    }
    if options.len() != 4 {
        return Err("Missing CLI option".into());
    }
    let mode = options["--mode"].clone();
    if !["golden", "ber", "perf", "stages"].contains(&mode.as_str()) {
        return Err("Unknown mode".into());
    }
    let workers = options["--workers"]
        .parse::<u64>()
        .map_err(|_| "workers must be positive u64")?;
    if workers == 0 || options["--workers"].starts_with('+') {
        return Err("workers must be positive u64".into());
    }
    let workers = usize::try_from(workers).map_err(|e| e.to_string())?;
    let bytes = fs::read(&options["--config"]).map_err(|e| e.to_string())?;
    let config = parse(&bytes)?;
    validate(&config, &mode)?;
    Ok(Arguments {
        config,
        bytes,
        mode,
        workers,
        output: PathBuf::from(&options["--out"]),
    })
}
fn capture(program: &str, args: &[&str], input: &[u8]) -> Result<String, String> {
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input)
        .map_err(|e| e.to_string())?;
    let result = child.wait_with_output().map_err(|e| e.to_string())?;
    if !result.status.success() {
        return Err("Metadata utility failed".into());
    }
    Ok(String::from_utf8(result.stdout)
        .map_err(|e| e.to_string())?
        .split_whitespace()
        .next()
        .ok_or("Empty metadata output")?
        .to_owned())
}
fn batches(
    pool: &rayon::ThreadPool,
    master: u64,
    point_index: u64,
    first: u64,
    last: u64,
    point: f64,
) -> Vec<Counts> {
    pool.install(|| {
        (0..(last - first) as usize)
            .into_par_iter()
            .with_max_len(1)
            .map(|i| {
                WORKER.with(|cell| {
                    cell.borrow_mut()
                        .as_mut()
                        .unwrap()
                        .batch(batch_seed(master, point_index, first + i as u64), point)
                })
            })
            .collect()
    })
}
fn execute(args: Arguments, setup_start: Instant) -> Result<(), String> {
    let cfg = Arc::new(Config::from(&args.config));
    let master = args.config["master_seed"].as_u64().unwrap();
    let project_root = root();
    let base = json!({"schema_version":1,"impl":"rust","mode":args.mode,
        "profile_id":args.config["profile_id"],"master_seed":master,"workers":args.workers,
        "git_sha":capture("git",&["-C",project_root.to_str().unwrap(),"rev-parse","HEAD"],&[])?,
        "config_sha256":capture("sha256sum",&[],&args.bytes)?});
    let mut records = Vec::new();
    if args.mode == "golden" {
        let mut worker = Worker::new(cfg);
        for entry in fs::read_dir(root().join("contract/golden")).map_err(|e| e.to_string())? {
            let path = entry.map_err(|e| e.to_string())?.path();
            if path.extension().and_then(|x| x.to_str()) != Some("json") {
                continue;
            }
            let vector = parse(&fs::read(path).map_err(|e| e.to_string())?)?;
            let mut record = base.clone();
            record["case_id"] = vector["case_id"].clone();
            record["outputs"] =
                worker.golden(vector["case_id"].as_str().unwrap(), &vector["inputs"])?;
            records.push(record);
        }
    } else {
        let (ready_tx, ready_rx) = mpsc::channel();
        let pool_config = cfg.clone();
        let pool = rayon::ThreadPoolBuilder::new()
            .num_threads(args.workers)
            .start_handler(move |_| {
                WORKER.with(|cell| *cell.borrow_mut() = Some(Worker::new(pool_config.clone())));
                let _ = ready_tx.send(());
            })
            .build()
            .map_err(|e| e.to_string())?;
        for _ in 0..args.workers {
            ready_rx.recv().map_err(|e| e.to_string())?;
        }
        let mut stage_worker = if args.mode == "stages" {
            Some(Worker::new(cfg))
        } else {
            None
        };
        let setup_s = setup_start.elapsed().as_secs_f64();
        let warm_start = Instant::now();
        batches(&pool, splitmix(master ^ 0x7761726d7570), 0, 0, 4, 10.);
        let warmup_s = warm_start.elapsed().as_secs_f64();
        if let Some(path) = std::env::var_os("BENCH_PHASE_PATH") {
            let mut phase = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)
                .map_err(|e| e.to_string())?;
            phase.write_all(b"work\n").map_err(|e| e.to_string())?;
        }
        let points = if args.mode == "ber" {
            args.config["ber"]["ebn0_db"]
                .as_array()
                .unwrap()
                .iter()
                .map(|x| x.as_f64().unwrap())
                .collect::<Vec<_>>()
        } else {
            vec![10.]
        };
        for (point_index, &point) in points.iter().enumerate() {
            let mut counts = Counts::default();
            let max_bits = args.config["ber"]["max_bits"].as_u64().unwrap();
            let limit = if args.mode == "ber" {
                max_bits.div_ceil(BATCH_BITS)
            } else if args.mode == "perf" {
                args.config["perf"]["n_batches"].as_u64().unwrap()
            } else {
                1
            };
            let start = Instant::now();
            let mut first = 0;
            let mut status = if args.mode == "ber" {
                "max_bits"
            } else {
                "fixed_work"
            };
            'work: while first < limit {
                let last = first + (limit - first).min((args.workers as u64 * 2).max(4));
                for result in batches(&pool, master, point_index as u64, first, last, point) {
                    counts.add(&result)?;
                    if args.mode == "ber" {
                        if counts.batches >= args.config["ber"]["min_batches"].as_u64().unwrap()
                            && counts.errors
                                >= args.config["ber"]["target_errors"].as_u64().unwrap()
                        {
                            status = "target_errors";
                            break 'work;
                        }
                        if counts.batches * BATCH_BITS >= max_bits {
                            break 'work;
                        }
                    }
                }
                first = last;
            }
            let timings = stage_worker
                .as_mut()
                .map(|w| w.stages(batch_seed(master, point_index as u64, 0), point));
            let work_s = start.elapsed().as_secs_f64();
            let mut record = base.clone();
            for (name,value) in json!({"ebn0_db":point,"n_batches":counts.batches,"n_symbols":counts.batches * dsp::SYMBOLS_PER_BATCH as u64,
                "n_bits":counts.batches*BATCH_BITS,"n_errors":counts.errors,"sum_batch_errors_sq":counts.squares,
                "n_symbols_with_errors":counts.symbols_with_errors,"zf_zero_count":counts.zeros,"status":status,
                "setup_s":setup_s,"warmup_s":warmup_s,"work_s":work_s}).as_object().unwrap(){record[name]=value.clone();}
            if let Some(timing) = timings {
                record["stage_ns_per_symbol"] = timing;
            }
            records.push(record);
        }
    }
    let temporary = args.output.with_file_name(format!(
        "{}.tmp.{}",
        args.output.file_name().unwrap().to_string_lossy(),
        std::process::id()
    ));
    let mut file = fs::File::create(&temporary).map_err(|e| e.to_string())?;
    for record in records {
        writeln!(file, "{}", record).map_err(|e| e.to_string())?;
    }
    file.flush().map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(temporary, args.output).map_err(|e| e.to_string())?;
    Ok(())
}
fn main() {
    let setup_start = Instant::now();
    let args = match arguments() {
        Ok(value) => value,
        Err(error) => {
            eprintln!("Invalid configuration: {error}");
            std::process::exit(2);
        }
    };
    if let Err(error) = execute(args, setup_start) {
        eprintln!("Execution failed: {error}");
        std::process::exit(1);
    }
}
