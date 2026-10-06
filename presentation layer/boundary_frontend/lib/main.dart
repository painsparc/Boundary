import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

void main() {
  runApp(const BoundaryApp());
}

class BoundaryApp extends StatelessWidget {
  const BoundaryApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Boundary Engine',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFFF5F5F7),
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.black),
        fontFamily: 'Roboto',
        useMaterial3: true,
      ),
      home: const BoundaryDashboard(),
    );
  }
}

class BoundaryDashboard extends StatefulWidget {
  const BoundaryDashboard({super.key});

  @override
  State<BoundaryDashboard> createState() => _BoundaryDashboardState();
}

class _BoundaryDashboardState extends State<BoundaryDashboard> {
  // Override at build/run time: --dart-define=BOUNDARY_API_URL=... --dart-define=BOUNDARY_ADMIN_KEY=...
  static const String apiUrl = String.fromEnvironment('BOUNDARY_API_URL', defaultValue: 'http://127.0.0.1:8000');
  static const String _adminKey = String.fromEnvironment('BOUNDARY_ADMIN_KEY');
  static const List<String> _allDestinations = ['third_party_llm', 'internal_fraud_system', 'marketing_analytics'];
  static const List<String> _allPurposes = ['customer_support', 'fraud_investigation', 'aggregate_analysis'];

  Map<String, List<String>> _routes = {};   // destination -> purposes that have a policy (from GET /routes)

  Map<String, String> get _jsonHeaders => {
        "Content-Type": "application/json",
        if (_adminKey.isNotEmpty) "X-API-Key": _adminKey,
      };

  @override
  void initState() {
    super.initState();
    _loadRoutes();
  }

  Future<void> _loadRoutes() async {
    try {
      final r = await http.get(Uri.parse("$apiUrl/routes"));
      if (r.statusCode == 200 && mounted) {
        final d = jsonDecode(r.body)['destinations'] as Map<String, dynamic>;
        setState(() => _routes = d.map((k, v) => MapEntry(k, List<String>.from(v))));
      }
    } catch (_) {/* fall back to the static lists */}
  }

  /// Intercept mode only offers combinations that have a policy; config mode offers all purposes.
  List<String> get _purposeOptions {
    final configured = _routes[_destination] ?? const <String>[];
    return (_isConfigMode || configured.isEmpty) ? _allPurposes : configured;
  }

  void _resetDraft() {
    _proposedRules = null;
    _lockedRules = {};
    _interceptResult = null;
  }

  void _onDestinationChanged(String? v) => setState(() {
        _destination = v!;
        if (!_purposeOptions.contains(_purpose)) _purpose = _purposeOptions.first;
        _resetDraft();   // rules proposed for another route must never be locked onto this one
      });

  void _onPurposeChanged(String? v) => setState(() {
        _purpose = v!;
        _resetDraft();
      });

  String _errorDetail(http.Response r) {
    try {
      final d = jsonDecode(r.body)['detail'];
      if (d is Map && d['violations'] is List) return (d['violations'] as List).join('\n');
      return d.toString();
    } catch (_) {
      return "HTTP ${r.statusCode}";
    }
  }

  Map<String, dynamic>? _parseInput() {
    try {
      final v = jsonDecode(_inputController.text);
      if (v is Map<String, dynamic>) return v;
    } catch (_) {}
    _showError("Input must be a valid JSON object.");
    return null;
  }

  
  bool _isConfigMode = false;
  String _destination = 'third_party_llm';
  String _purpose = 'customer_support';

  // Config State
  final TextEditingController _contextController = TextEditingController(text: "Fintech app handling user payments and medical reimbursement support tickets.");
  bool _isGeneratingPolicy = false;
  List<dynamic>? _proposedRules;
  Map<String, String> _lockedRules = {};

  // Intercept State
  final TextEditingController _inputController = TextEditingController(
    text: '''{
  "name": "Test User",
  "age": 43,
  "city": "Pune",
  "occupation": "Systems Architect",
  "bank_account": "1234-5678-9012",
  "government_id": "GOV-88221",
  "free_text_note": "Requesting medical reimbursement for a recent cardiology appointment."
}'''
  );
  bool _isIntercepting = false;
  Map<String, dynamic>? _interceptResult;

  // --- API CALLS ---

  Future<void> _generateAIPolicy() async {
    final sampleData = _parseInput();
    if (sampleData == null) return;
    setState(() => _isGeneratingPolicy = true);
    try {
      final response = await http.post(
        Uri.parse("$apiUrl/generate-policy"),
        headers: _jsonHeaders,
        body: jsonEncode({
          "app_context": _contextController.text,
          "destination": _destination,
          "purpose": _purpose,
          "sample_fields": sampleData.keys.toList()
        }),
      );

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        setState(() {
          _proposedRules = data['rules'];
          // Pre-fill user edit map
          _lockedRules = { for (var item in _proposedRules!) item['field']: item['action'] };
        });
      } else {
        _showError("AI generation failed: ${_errorDetail(response)}");
      }
    } catch (e) {
      _showError("Could not reach the Boundary API at $apiUrl.");
    } finally {
      if (mounted) setState(() => _isGeneratingPolicy = false);
    }
  }

  Future<void> _lockPolicy() async {
    try {
      final response = await http.post(
        Uri.parse("$apiUrl/save-policy"),
        headers: _jsonHeaders,
        body: jsonEncode({
          "destination": _destination,
          "purpose": _purpose,
          "rules": _lockedRules
        }),
      );
      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text("Policy Locked Successfully. Engine reloaded."), backgroundColor: Colors.green));
        setState(() => _isConfigMode = false); // Switch back to live intercept
        _loadRoutes();
      } else {
        _showError("Policy rejected: ${_errorDetail(response)}");
      }
    } catch (e) {
      _showError("Failed to save policy: could not reach $apiUrl.");
    }
  }

  Future<void> _runBoundaryEngine() async {
    final payload = _parseInput();
    if (payload == null) return;
    setState(() => _isIntercepting = true);
    try {
      final response = await http.post(
        Uri.parse("$apiUrl/protect"),
        headers: _jsonHeaders,
        body: jsonEncode({"data": payload, "destination": _destination, "purpose": _purpose}),
      );
      if (response.statusCode == 200) {
        setState(() => _interceptResult = jsonDecode(response.body));
      } else {
        _showError(_errorDetail(response));
      }
    } catch (e) {
      _showError("Could not reach the Boundary API at $apiUrl.");
    } finally {
      if (mounted) setState(() => _isIntercepting = false);
    }
  }

  void _showError(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message, style: const TextStyle(color: Colors.white)), backgroundColor: Colors.red));
  }

  // --- UI BUILDERS ---

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.white,
        elevation: 0,
        title: const Text("BOUNDARY", style: TextStyle(letterSpacing: 4.0, fontWeight: FontWeight.w900, color: Colors.black)),
        centerTitle: true,
        actions: [
          Row(
            children: [
              const Text("SETUP MODE", style: TextStyle(fontWeight: FontWeight.bold, fontSize: 12)),
              Switch(
                value: _isConfigMode,
                activeColor: Colors.black,
                onChanged: (val) => setState(() {
                  _isConfigMode = val;
                  if (!_purposeOptions.contains(_purpose)) _purpose = _purposeOptions.first;
                }),
              ),
              const SizedBox(width: 24),
            ],
          )
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(32.0),
        child: _isConfigMode ? _buildConfigMode() : _buildInterceptMode(),
      ),
    );
  }

  Widget _buildConfigMode() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Left: Context Input
        Expanded(
          flex: 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("1. Define System Context", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(child: _buildDropdown("Destination", _destination, _allDestinations, _onDestinationChanged)),
                  const SizedBox(width: 16),
                  Expanded(child: _buildDropdown("Purpose", _purpose, _purposeOptions, _onPurposeChanged)),
                ],
              ),
              const SizedBox(height: 24),
              const Text("App Context (for AI)", style: TextStyle(fontSize: 12, color: Colors.grey, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              TextField(
                controller: _contextController,
                maxLines: 3,
                decoration: InputDecoration(filled: true, fillColor: Colors.white, border: OutlineInputBorder(borderRadius: BorderRadius.circular(8), borderSide: BorderSide(color: Colors.grey.shade300))),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: ElevatedButton(
                  onPressed: _isGeneratingPolicy ? null : _generateAIPolicy,
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.blueAccent, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
                  child: _isGeneratingPolicy ? const CircularProgressIndicator(color: Colors.white) : const Text("ASK AI TO PROPOSE POLICY", style: TextStyle(letterSpacing: 1.0, fontWeight: FontWeight.bold)),
                ),
              )
            ],
          ),
        ),
        const SizedBox(width: 48),
        // Right: Human-in-the-Loop Review
        Expanded(
          flex: 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("2. Human-in-the-Loop Review", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Expanded(
                child: Container(
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.grey.shade300)),
                  child: _proposedRules == null 
                    ? const Center(child: Text("Generate policy to review.", style: TextStyle(color: Colors.grey)))
                    : ListView.separated(
                        itemCount: _proposedRules!.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (context, index) {
                          final rule = _proposedRules![index];
                          final field = rule['field'];
                          return ListTile(
                            title: Text(field, style: const TextStyle(fontWeight: FontWeight.bold)),
                            subtitle: Text(rule['reason'], style: const TextStyle(fontSize: 12)),
                            trailing: DropdownButton<String>(
                              value: _lockedRules[field],
                              items: ['ALLOW', 'REDACT', 'BLOCK', 'MASK', 'GENERALIZE', 'REMOVE'].map((e) => DropdownMenuItem(value: e, child: Text(e, style: const TextStyle(fontWeight: FontWeight.bold)))).toList(),
                              onChanged: (val) {
                                setState(() => _lockedRules[field] = val!);
                              },
                            ),
                          );
                        },
                      ),
                ),
              ),
              const SizedBox(height: 16),
              if (_proposedRules != null)
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton(
                    onPressed: _lockPolicy,
                    style: ElevatedButton.styleFrom(backgroundColor: Colors.black, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
                    child: const Text("CONFIRM & LOCK POLICY", style: TextStyle(letterSpacing: 1.5, fontWeight: FontWeight.bold)),
                  ),
                )
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildInterceptMode() {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Left Column (Data Input)
        Expanded(
          flex: 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("1. Integration Route", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(child: _buildDropdown("Destination", _destination, _allDestinations, _onDestinationChanged)),
                  const SizedBox(width: 16),
                  Expanded(child: _buildDropdown("Purpose", _purpose, _purposeOptions, _onPurposeChanged)),
                ],
              ),
              const SizedBox(height: 24),
              const Text("2. Raw Application Data", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Expanded(
                child: Container(
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.grey.shade300)),
                  padding: const EdgeInsets.all(16),
                  child: TextField(
                    controller: _inputController,
                    maxLines: null,
                    expands: true,
                    style: const TextStyle(fontFamily: 'monospace', fontSize: 14),
                    decoration: const InputDecoration(border: InputBorder.none),
                  ),
                ),
              ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 56,
                child: ElevatedButton(
                  onPressed: _isIntercepting ? null : _runBoundaryEngine,
                  style: ElevatedButton.styleFrom(backgroundColor: Colors.black, foregroundColor: Colors.white, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8))),
                  child: _isIntercepting ? const CircularProgressIndicator(color: Colors.white) : const Text("EXECUTE BOUNDARY INTERCEPT", style: TextStyle(letterSpacing: 1.5, fontWeight: FontWeight.bold)),
                ),
              )
            ],
          ),
        ),
        const SizedBox(width: 48),
        // Right Column (Output)
        Expanded(
          flex: 1,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text("3. Safe Network Payload (Output)", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Expanded(
                flex: 2,
                child: Container(
                  width: double.infinity,
                  decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(12)),
                  padding: const EdgeInsets.all(24),
                  child: SingleChildScrollView(
                    child: Text(
                      _interceptResult != null ? const JsonEncoder.withIndent('  ').convert(_interceptResult!['data']) : "Awaiting execution...",
                      style: const TextStyle(fontFamily: 'monospace', fontSize: 14, color: Colors.greenAccent),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 32),
              const Text("Engine Intelligence & Risk Profiling", style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 16),
              Expanded(
                flex: 2,
                child: Container(
                  decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(12), border: Border.all(color: Colors.grey.shade300)),
                  padding: const EdgeInsets.all(16),
                  child: _interceptResult == null 
                    ? const Center(child: Text("Run the engine.", style: TextStyle(color: Colors.grey)))
                    : ListView.builder(
                        itemCount: (_interceptResult!['explanations'] as List).length,
                        itemBuilder: (context, index) {
                          final exp = _interceptResult!['explanations'][index];
                          return ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text("[${exp['field']}] ➔ ${exp['action']}", style: const TextStyle(fontWeight: FontWeight.bold)),
                            subtitle: Text("${exp['reason']}\nMethod: ${exp['detection_method']} | Risk: ${exp['risk']}"),
                            isThreeLine: true,
                          );
                        },
                      ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildDropdown(String label, String value, List<String> items, Function(String?) onChanged) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, color: Colors.grey, fontWeight: FontWeight.bold)),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(8), border: Border.all(color: Colors.grey.shade300)),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              value: value,
              isExpanded: true,
              items: items.map((e) => DropdownMenuItem(value: e, child: Text(e, style: const TextStyle(fontSize: 14)))).toList(),
              onChanged: onChanged,
            ),
          ),
        ),
      ],
    );
  }
}