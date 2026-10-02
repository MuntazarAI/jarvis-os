from jarvis.neural import LIFNeuron, NeuralNervousSystem, SpikingNetwork, Synapse
from jarvis.neural.plasticity import HomeostaticPlasticity, STDPRule, exponential_decay
from jarvis.neural.system import NeuralEvent


def test_lif_neuron_leaks_and_fires():
    neuron = LIFNeuron(threshold=1.0, leak=0.5)
    assert neuron.step(0.8) is False
    assert neuron.potential == 0.8
    assert neuron.step(0.0) is False
    assert neuron.potential == 0.4
    assert neuron.step(0.7) is False
    assert neuron.potential == 0.8999999999999999
    assert neuron.step(0.6) is True
    assert neuron.potential == 0.0
    assert neuron.spikes == 1


def test_spiking_network_routes_spikes():
    net = SpikingNetwork(2)
    syn = net.connect(0, 1, 1.0)
    assert isinstance(syn, Synapse)
    assert net.step({0: 1.0}) == [0]
    assert net.step() == [1]


def test_delayed_synapse_arrives_later():
    net = SpikingNetwork(2)
    net.connect(0, 1, 1.0, delay=2)
    assert net.step({0: 1.0}) == [0]
    assert net.step() == []
    assert net.step() == [1]


def test_network_reset_clears_state():
    net = SpikingNetwork(2)
    net.connect(0, 1, 1.0)
    net.step({0: 1.0})
    net.step()
    net.reset()
    assert net.time == 0
    assert all(n.potential == 0.0 and n.spikes == 0 for n in net.neurons)


def test_neural_system_emits_typed_output_events():
    system = NeuralNervousSystem(2, 2, 1)
    outputs = system.step([NeuralEvent("input:0", 1.0), NeuralEvent("input:1", 1.0)])
    assert outputs == []
    assert system.step([]) == []
    outputs = system.step([])
    assert all(event.channel == "output:0" for event in outputs)


def test_neural_system_rejects_invalid_input_channel():
    system = NeuralNervousSystem(1, 1, 1)
    try:
        system.step([NeuralEvent("input:nope", 1.0)])
    except ValueError as exc:
        assert "invalid neural input channel" in str(exc)
    else:
        raise AssertionError("invalid input channel was accepted")


def test_stdp_is_bounded():
    rule = STDPRule()
    assert rule.update(2.0, 0, 1) == 2.0
    assert rule.update(-2.0, 1, 0) == -2.0
    assert rule.update(1.0, 0, 100) == 1.0


def test_homeostatic_plasticity_is_bounded():
    rule = HomeostaticPlasticity()
    assert rule.update_threshold(0.1, 100.0) <= 5.0
    assert rule.update_threshold(5.0, -100.0) >= 0.1


def test_exponential_decay():
    assert 0 < exponential_decay(1.0, 10.0) < 1.0
