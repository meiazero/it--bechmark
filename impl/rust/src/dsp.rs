use num_complex::Complex64 as Complex;
use rand::{Rng, SeedableRng, rngs::SmallRng};
use rand_distr::{Distribution, StandardNormal};
use rustfft::{Fft, FftPlanner};
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::Instant;

pub const FFT_SIZE: usize = 256;
pub const CP_LENGTH: usize = 32;
pub const SAMPLES_WITH_CP: usize = FFT_SIZE + CP_LENGTH;
pub const SYMBOLS_PER_BATCH: usize = 256;
pub const BITS_PER_OFDM_SYMBOL: usize = 672;
pub const BITS_PER_BATCH: u64 = (SYMBOLS_PER_BATCH * BITS_PER_OFDM_SYMBOL) as u64;
pub const SYMBOL_ENERGY: f64 = 216.;

pub type Values = Vec<Complex>;
pub fn splitmix(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    value ^ (value >> 31)
}
pub fn batch_seed(master: u64, point: u64, batch: u64) -> u64 {
    splitmix(splitmix(splitmix(master) ^ point) ^ batch)
}
pub fn decode(input: &Value) -> Values {
    input
        .as_array()
        .unwrap()
        .iter()
        .map(|x| Complex::new(x[0].as_f64().unwrap(), x[1].as_f64().unwrap()))
        .collect()
}
pub fn encode(values: &[Complex]) -> Value {
    json!(values.iter().map(|x| [x.re, x.im]).collect::<Vec<_>>())
}
pub fn bits_from(input: &Value) -> Vec<u8> {
    input
        .as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_u64().unwrap() as u8)
        .collect()
}
pub fn map_qam(bits: &[u8]) -> Values {
    let levels = [-3., -1., 3., 1.];
    bits.as_chunks::<4>()
        .0
        .iter()
        .map(|b| {
            Complex::new(
                levels[(2 * b[0] + b[1]) as usize],
                levels[(2 * b[2] + b[3]) as usize],
            ) / 10f64.sqrt()
        })
        .collect()
}
pub fn demap(values: &[Complex]) -> Vec<u8> {
    values
        .iter()
        .flat_map(|x| [x.re, x.im])
        .flat_map(|axis| {
            let scaled = axis * 10f64.sqrt();
            [
                u8::from(scaled >= 0.),
                u8::from((-2. ..2.).contains(&scaled)),
            ]
        })
        .collect()
}
pub fn add_cp(values: &[Complex]) -> Values {
    values[FFT_SIZE - CP_LENGTH..]
        .iter()
        .chain(values.iter())
        .copied()
        .collect()
}
pub fn remove_cp(values: &[Complex]) -> Values {
    values[CP_LENGTH..SAMPLES_WITH_CP].to_vec()
}
pub fn convolve(values: &[Complex], taps: &[Complex]) -> Values {
    let mut output = vec![Complex::new(0., 0.); values.len()];
    // Each tap visits contiguous samples; each sample still sums taps in order.
    for (delay, &tap) in taps.iter().take(values.len()).enumerate() {
        for (received, &transmitted) in output[delay..].iter_mut().zip(values.iter()) {
            *received += tap * transmitted;
        }
    }
    output
}
pub fn response(taps: &[Complex]) -> Values {
    // Channel gains use the unscaled tap DFT, unlike the unitary signal FFTs.
    (0..FFT_SIZE)
        .map(|k| {
            taps.iter()
                .enumerate()
                .map(|(l, tap)| {
                    *tap * Complex::from_polar(
                        1.,
                        -2. * std::f64::consts::PI * k as f64 * l as f64 / FFT_SIZE as f64,
                    )
                })
                .sum()
        })
        .collect()
}
pub fn equalize(data: &[Complex], estimates: &[Complex]) -> (Values, u64) {
    // Exact zeros are counted; no clipping changes the ZF noise enhancement.
    let zeros = estimates
        .iter()
        .filter(|&&x| x == Complex::new(0., 0.))
        .count() as u64;
    let values = data
        .iter()
        .zip(estimates)
        .map(|(&x, &h)| {
            if h == Complex::new(0., 0.) {
                Complex::new(0., 0.)
            } else {
                x / h
            }
        })
        .collect();
    (values, zeros)
}
pub fn noise_variance(point: f64) -> Result<f64, String> {
    let value = SYMBOL_ENERGY / (BITS_PER_OFDM_SYMBOL as f64 * 10f64.powf(point / 10.));
    if !value.is_finite() || value <= 0. {
        return Err("Eb/N0 exceeds the finite noise range".into());
    }
    Ok(value)
}

pub struct Config {
    pub data_indices: Vec<usize>,
    pub pilot_indices: Vec<usize>,
    pub pilot_values: Vec<f64>,
    pub tap_scales: Vec<f64>,
    pub interpolation: Vec<(usize, usize, f64)>,
    pub awgn_channel: bool,
    pub perfect_csi: bool,
    pub repetitions: u64,
}
impl Config {
    pub fn from(value: &Value) -> Self {
        let bins: Vec<i64> = value["pilot_bins"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_i64().unwrap())
            .collect();
        let data_bins: Vec<i64> = value["data_bins"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| x.as_i64().unwrap())
            .collect();
        Self {
            data_indices: data_bins
                .iter()
                .map(|x| x.rem_euclid(FFT_SIZE as i64) as usize)
                .collect(),
            pilot_indices: bins
                .iter()
                .map(|x| x.rem_euclid(FFT_SIZE as i64) as usize)
                .collect(),
            pilot_values: value["pilots"]
                .as_array()
                .unwrap()
                .iter()
                .map(|x| x.as_f64().unwrap())
                .collect(),
            tap_scales: value["pdp"]
                .as_array()
                .unwrap()
                .iter()
                .map(|x| (x.as_f64().unwrap() / 2.).sqrt())
                .collect(),
            // Physical bin spacing spans DC; wrapped FFT indices cannot define it.
            interpolation: data_bins
                .iter()
                .map(|&k| {
                    let right = bins.partition_point(|&p| p <= k);
                    let left = right - 1;
                    (
                        left,
                        right,
                        (k - bins[left]) as f64 / (bins[right] - bins[left]) as f64,
                    )
                })
                .collect(),
            awgn_channel: value["channel"] == "awgn",
            perfect_csi: value["csi"] == "perfect",
            repetitions: value["stages"]["repetitions"].as_u64().unwrap(),
        }
    }
    pub fn grid(&self, data: &[Complex]) -> Values {
        let mut output = vec![Complex::new(0., 0.); FFT_SIZE];
        for (&index, &value) in self.data_indices.iter().zip(data) {
            output[index] = value;
        }
        for (&index, &value) in self.pilot_indices.iter().zip(&self.pilot_values) {
            output[index] = Complex::new(value, 0.);
        }
        output
    }
    pub fn extract(&self, spectrum: &[Complex]) -> Values {
        self.data_indices.iter().map(|&i| spectrum[i]).collect()
    }
    pub fn estimate(&self, spectrum: &[Complex]) -> (Values, Values) {
        let pilots: Values = self
            .pilot_indices
            .iter()
            .zip(&self.pilot_values)
            .map(|(&i, &p)| spectrum[i] / p)
            .collect();
        let estimates = self
            .interpolation
            .iter()
            .map(|&(left, right, fraction)| {
                pilots[left] + fraction * (pilots[right] - pilots[left])
            })
            .collect();
        (pilots, estimates)
    }
}

#[derive(Clone, Default)]
pub struct Counts {
    pub batches: u64,
    pub errors: u64,
    pub squares: u64,
    pub symbols_with_errors: u64,
    pub zeros: u64,
}
impl Counts {
    pub fn add(&mut self, other: &Self) -> Result<(), String> {
        for (target, value) in [
            (&mut self.batches, other.batches),
            (&mut self.errors, other.errors),
            (&mut self.squares, other.squares),
            (&mut self.symbols_with_errors, other.symbols_with_errors),
            (&mut self.zeros, other.zeros),
        ] {
            *target = target.checked_add(value).ok_or("u64 counter overflow")?;
        }
        Ok(())
    }
    pub fn decide(values: &[Complex], original_bits: &[u8]) -> Self {
        let errors = demap(values)
            .iter()
            .zip(original_bits)
            .filter(|(left, right)| left != right)
            .count() as u64;
        Self {
            errors,
            symbols_with_errors: u64::from(errors > 0),
            ..Self::default()
        }
    }
}
// ponytail: retain readable symbol-sized vectors after M8; full worker buffer
// reuse belongs to a separate optimized benchmark revision.
pub struct Worker {
    pub config: Arc<Config>,
    rng: SmallRng,
    forward: Arc<dyn Fft<f64>>,
    inverse: Arc<dyn Fft<f64>>,
    scratch: Values,
}
impl Worker {
    pub fn new(config: Arc<Config>) -> Self {
        let mut planner = FftPlanner::new();
        let forward = planner.plan_fft_forward(FFT_SIZE);
        let inverse = planner.plan_fft_inverse(FFT_SIZE);
        let size = forward
            .get_inplace_scratch_len()
            .max(inverse.get_inplace_scratch_len());
        Self {
            config,
            rng: SmallRng::seed_from_u64(0),
            forward,
            inverse,
            scratch: vec![Complex::new(0., 0.); size],
        }
    }
    pub fn transform(&mut self, values: &[Complex], inverse: bool) -> Values {
        let mut output = values.to_vec();
        let plan = if inverse {
            &self.inverse
        } else {
            &self.forward
        };
        // rustfft leaves both transforms unscaled; the contract requires 1/sqrt(N).
        plan.process_with_scratch(&mut output, &mut self.scratch);
        for x in &mut output {
            *x /= (FFT_SIZE as f64).sqrt();
        }
        output
    }
    fn bits(&mut self) -> Vec<u8> {
        (0..BITS_PER_OFDM_SYMBOL)
            .map(|_| u8::from(self.rng.random::<bool>()))
            .collect()
    }
    fn taps(&mut self) -> Values {
        if self.config.awgn_channel {
            return vec![Complex::new(1., 0.)];
        }
        self.config
            .tap_scales
            .iter()
            .map(|&scale| {
                let real: f64 = StandardNormal.sample(&mut self.rng);
                let imag: f64 = StandardNormal.sample(&mut self.rng);
                Complex::new(real, imag) * scale
            })
            .collect()
    }
    fn awgn(&mut self, values: &[Complex], n0: f64) -> Values {
        values
            .iter()
            .map(|&x| {
                let real: f64 = StandardNormal.sample(&mut self.rng);
                let imag: f64 = StandardNormal.sample(&mut self.rng);
                x + Complex::new(real, imag) * (n0 / 2.).sqrt()
            })
            .collect()
    }
    pub fn batch(&mut self, seed: u64, point: f64) -> Counts {
        self.rng = SmallRng::seed_from_u64(seed);
        let n0 = noise_variance(point).unwrap();
        let mut counts = Counts::default();
        for _ in 0..SYMBOLS_PER_BATCH {
            let original_bits = self.bits();
            let transmit_grid = self.config.grid(&map_qam(&original_bits));
            let transmit_time = self.transform(&transmit_grid, true);
            let prefixed = add_cp(&transmit_time);
            let channel_taps = self.taps();
            let channel_output = convolve(&prefixed, &channel_taps);
            let noisy = self.awgn(&channel_output, n0);
            let received_grid = self.transform(&remove_cp(&noisy), false);
            let estimates = if self.config.perfect_csi {
                self.config.extract(&response(&channel_taps))
            } else {
                self.config.estimate(&received_grid).1
            };
            let (equalized, zeros) = equalize(&self.config.extract(&received_grid), &estimates);
            let symbol_counts = Counts::decide(&equalized, &original_bits);
            counts.errors += symbol_counts.errors;
            counts.symbols_with_errors += symbol_counts.symbols_with_errors;
            counts.zeros += zeros;
        }
        counts.batches = 1;
        counts.squares = counts.errors * counts.errors;
        counts
    }
    pub fn golden(&mut self, id: &str, input: &Value) -> Result<Value, String> {
        match id {
            "qam_map" => Ok(json!({"symbols":encode(&map_qam(&bits_from(&input["bits"])))})),
            "demap" => Ok(json!({"bits":demap(&decode(&input["symbols"]))})),
            "grid" => {
                let spectrum = self.config.grid(&decode(&input["symbols"]));
                Ok(
                    json!({"spectrum":encode(&spectrum),"data":encode(&self.config.extract(&spectrum)),
                    "pilots":encode(&self.config.pilot_indices.iter().map(|&i|spectrum[i]).collect::<Values>())}),
                )
            }
            "transforms" | "fft_impulse" => {
                let values = decode(&input["values"]);
                Ok(
                    json!({"fft":encode(&self.transform(&values,false)),"ifft":encode(&self.transform(&values,true))}),
                )
            }
            "cp" => {
                let cp = add_cp(&decode(&input["values"]));
                Ok(json!({"with_cp":encode(&cp),"without_cp":encode(&remove_cp(&cp))}))
            }
            "channel" => {
                let taps = decode(&input["taps"]);
                Ok(
                    json!({"convolved":encode(&convolve(&decode(&input["values"]),&taps)),"response":encode(&response(&taps))}),
                )
            }
            "estimation" => {
                let (pilots, estimates) = self.config.estimate(&decode(&input["spectrum"]));
                Ok(json!({"pilot_estimates":encode(&pilots),"data_estimates":encode(&estimates)}))
            }
            "zf" => {
                let (equalized, zeros) =
                    equalize(&decode(&input["data"]), &decode(&input["estimates"]));
                Ok(json!({"equalized":encode(&equalized),"zf_zero_count":zeros}))
            }
            "noise_seed" => Ok(json!({
                "N0": input["ebn0_db"].as_array().unwrap().iter().map(|p|noise_variance(p.as_f64().unwrap()).unwrap()).collect::<Vec<_>>(),
                "splitmix_outputs": input["splitmix_inputs"].as_array().unwrap().iter().map(|s|splitmix(s.as_u64().unwrap())).collect::<Vec<_>>(),
                "batch_seeds": input["batch_seed_inputs"].as_array().unwrap().iter().map(|s|batch_seed(s[0].as_u64().unwrap(),s[1].as_u64().unwrap(),s[2].as_u64().unwrap())).collect::<Vec<_>>()
            })),
            "end_to_end" => {
                let original_bits = bits_from(&input["bits"]);
                let taps = decode(&input["taps"]);
                let spectrum = self.config.grid(&map_qam(&original_bits));
                let time = self.transform(&spectrum, true);
                let cp = add_cp(&time);
                let received: Values = convolve(&cp, &taps)
                    .iter()
                    .zip(decode(&input["noise"]))
                    .map(|(x, n)| x + n)
                    .collect();
                let received_grid = self.transform(&remove_cp(&received), false);
                let (pilots, estimates) = self.config.estimate(&received_grid);
                let data = self.config.extract(&received_grid);
                let (equalized, zeros) = equalize(&data, &estimates);
                let perfect = equalize(&data, &self.config.extract(&response(&taps))).0;
                let counts = Counts::decide(&equalized, &original_bits);
                Ok(
                    json!({"spectrum":encode(&spectrum),"time":encode(&time),"with_cp":encode(&cp),
                    "received":encode(&received),"received_fft":encode(&received_grid),"pilot_estimates":encode(&pilots),
                    "data_estimates":encode(&estimates),"equalized":encode(&equalized),"bits":demap(&equalized),
                    "perfect_bits":demap(&perfect),"n_errors":counts.errors,"zf_zero_count":zeros}),
                )
            }
            _ => Err("Unknown golden case".into()),
        }
    }
    pub fn stages(&mut self, seed: u64, point: f64) -> Value {
        self.rng = SmallRng::seed_from_u64(seed);
        let n0 = noise_variance(point).unwrap();
        let mut original_bits = Vec::new();
        let mut qam_symbols = Vec::new();
        let mut spectra = Vec::new();
        let mut times = Vec::new();
        let mut cps = Vec::new();
        let mut channel_taps = Vec::new();
        let mut received = Vec::new();
        let mut noisy = Vec::new();
        let mut stripped = Vec::new();
        let mut received_grid = Vec::new();
        let mut estimates = Vec::new();
        let mut equalized = Vec::new();
        for _ in 0..SYMBOLS_PER_BATCH {
            original_bits.push(self.bits());
            qam_symbols.push(map_qam(original_bits.last().unwrap()));
            spectra.push(self.config.grid(qam_symbols.last().unwrap()));
            times.push(self.transform(spectra.last().unwrap(), true));
            cps.push(add_cp(times.last().unwrap()));
            channel_taps.push(self.taps());
            received.push(convolve(cps.last().unwrap(), channel_taps.last().unwrap()));
            noisy.push(self.awgn(received.last().unwrap(), n0));
            stripped.push(remove_cp(noisy.last().unwrap()));
            received_grid.push(self.transform(stripped.last().unwrap(), false));
            estimates.push(self.config.estimate(received_grid.last().unwrap()).1);
            equalized.push(
                equalize(
                    &self.config.extract(received_grid.last().unwrap()),
                    estimates.last().unwrap(),
                )
                .0,
            );
        }
        let mut output = json!({});
        for name in [
            "bits",
            "qam_map",
            "grid",
            "ifft",
            "cp_add",
            "channel_conv",
            "awgn",
            "cp_remove",
            "fft",
            "chan_est",
            "zf",
            "demap_count",
            "e2e",
        ] {
            let mut samples = Vec::new();
            for r in 0..self.config.repetitions {
                let start = Instant::now();
                if name == "e2e" {
                    std::hint::black_box(self.batch(batch_seed(seed, 0, r), point));
                } else {
                    for i in 0..SYMBOLS_PER_BATCH {
                        match name {
                            "bits" => {
                                std::hint::black_box(self.bits());
                            }
                            "qam_map" => {
                                std::hint::black_box(map_qam(&original_bits[i]));
                            }
                            "grid" => {
                                std::hint::black_box(self.config.grid(&qam_symbols[i]));
                            }
                            "ifft" => {
                                std::hint::black_box(self.transform(&spectra[i], true));
                            }
                            "cp_add" => {
                                std::hint::black_box(add_cp(&times[i]));
                            }
                            "channel_conv" => {
                                std::hint::black_box(convolve(&cps[i], &channel_taps[i]));
                            }
                            "awgn" => {
                                std::hint::black_box(self.awgn(&received[i], n0));
                            }
                            "cp_remove" => {
                                std::hint::black_box(remove_cp(&noisy[i]));
                            }
                            "fft" => {
                                std::hint::black_box(self.transform(&stripped[i], false));
                            }
                            "chan_est" => {
                                std::hint::black_box(self.config.estimate(&received_grid[i]));
                            }
                            "zf" => {
                                std::hint::black_box(equalize(
                                    &self.config.extract(&received_grid[i]),
                                    &estimates[i],
                                ));
                            }
                            "demap_count" => {
                                std::hint::black_box(Counts::decide(
                                    &equalized[i],
                                    &original_bits[i],
                                ));
                            }
                            _ => unreachable!(),
                        }
                    }
                }
                samples.push(start.elapsed().as_secs_f64() * 1e9 / SYMBOLS_PER_BATCH as f64);
            }
            samples.sort_by(f64::total_cmp);
            output[name] =
                json!((samples[(samples.len() - 1) / 2] + samples[samples.len() / 2]) / 2.);
        }
        output
    }
}
